#!/usr/bin/env python3
"""Issue #71: read-only time/resource metrics from existing private records.

Reads a runner set folder (`events.jsonl`) and/or a supervisor day folder
(`ledger.json`, `invocation-*/start.json|end.json`). Writes nothing; prints JSON
with durations, counts and CPU/RSS only — never market data, paths or commands.
LLM token usage is not recorded by the supervisor today (see #71).
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_set import Blocked, decode_json, load, read, require, safe_path  # noqa: E402


def span(a, b):
    return None if a is None or b is None else round(b - a, 3)


def set_metrics(folder):
    folder = safe_path(Path(folder).resolve(), private=True, directory=True)
    events = [decode_json(line) for line in read(folder / 'events.jsonl').splitlines()]
    require(events and events[0]['event'] == 'init', 'missing_init')
    first = lambda event, **f: next((e['time'] for e in events if e['event'] == event
                                    and all(e.get(k) == v for k, v in f.items())), None)
    starts = {e['run_id']: e for e in events if e['event'] == 'start'}
    trials = []
    for e in events:
        if e['event'] == 'end' and e['run_id'] in starts:
            usage = e.get('rusage') or {}
            trials.append({'role': starts[e['run_id']]['role'], 'status': e['status'],
                           'wall_seconds': span(starts[e['run_id']]['time'], e['time']),
                           'cpu_seconds': round(usage['user_seconds'] + usage['system_seconds'], 6) if usage else None,
                           'max_rss_bytes': usage.get('max_rss_bytes')})
    first_start = min((e['time'] for e in starts.values()), default=None)
    last_end = max((e['time'] for e in events if e['event'] == 'end'), default=None)
    finish = first('complete') or first('blocked')
    cpu = [t['cpu_seconds'] for t in trials if t['cpu_seconds'] is not None]
    return {
        'set_id': folder.name,
        'state': 'completed' if first('complete') else 'blocked' if first('blocked') else 'open',
        'attempts': len(starts), 'trials': trials,
        'phases_seconds': {
            'plan_checkpoint_wait': span(events[0]['time'], first('checkpoint', kind='plan')),
            'trials': span(first_start, last_end),
            'selection_checkpoint_wait': span(first('selection'), first('checkpoint', kind='selection')),
            'evaluate_finalize': span(first('checkpoint', kind='selection'), first('complete')),
            'total': span(events[0]['time'], finish or events[-1]['time']),
        },
        'trial_wall_seconds_sum': round(sum(t['wall_seconds'] for t in trials), 3),
        'trial_cpu_seconds_sum': round(sum(cpu), 6) if cpu else None,
        'trial_max_rss_bytes': max((t['max_rss_bytes'] for t in trials if t['max_rss_bytes']), default=None),
    }


def day_metrics(folder):
    folder = safe_path(Path(folder).resolve(), private=True, directory=True)
    ledger = load(folder / 'ledger.json')
    kinds = {}
    for inv in sorted(folder.glob('invocation-*')):
        start = load(inv / 'start.json')
        end = load(inv / 'end.json') if (inv / 'end.json').exists() else None
        k = kinds.setdefault(start['kind'], {'count': 0, 'open': 0, 'failed': 0, 'timed_out': 0,
                                             'seconds_sum': 0.0, 'seconds_max': 0.0})
        k['count'] += 1
        if end is None:
            k['open'] += 1; continue
        seconds = end['ended_at'] - start['started_at']
        k['seconds_sum'] = round(k['seconds_sum'] + seconds, 3); k['seconds_max'] = round(max(k['seconds_max'], seconds), 3)
        k['failed'] += end['exit_code'] != 0; k['timed_out'] += bool(end['timed_out'])
    return {'date': folder.name, 'status': ledger['status'], 'launches': ledger['launches'],
            'acquisition_attempts': ledger['acquisition_attempts'],
            'ledger_span_seconds': span(ledger['started_epoch'], ledger['updated_epoch']),
            'invocations': kinds, 'llm_tokens': None}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--set', dest='set_folder', help='absolute private runner set folder')
    p.add_argument('--day', dest='day_folder', help='absolute private supervisor day folder')
    a = p.parse_args(argv)
    if not (a.set_folder or a.day_folder): p.error('give --set and/or --day')
    out = {}
    try:
        if a.set_folder: out['set'] = set_metrics(a.set_folder)
        if a.day_folder: out['day'] = day_metrics(a.day_folder)
    except Blocked as error:
        print('blocked: ' + str(error), file=sys.stderr); return 2
    print(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1))


if __name__ == '__main__':
    sys.exit(main())
