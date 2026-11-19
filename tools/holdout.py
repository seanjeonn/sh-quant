#!/usr/bin/env python3
"""Sealed forward holdout (#109, design docs/holdout-design.md).

seal: derive a private research input that keeps only bars dated < S from a
      verified complete snapshot (new manifest, cutoff_exclusive = S).
open: evaluate a completed sealed set's selected candidate once on bars >= S
      with holdout_forward_v1. Only `accept` sets, at least MIN_BARS bars per
      market, at most MAX_OPENINGS per S. The private ledger records `open`
      before the engine runs, so a crash after seeing results cannot reopen.
stdout is status-only; metrics stay in private files.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_set as rs
from research_set import Blocked, digest, encode, immutable, load, read, require

MIN_BARS = 126
MAX_OPENINGS = 3


def private_dir(path):
    rs.safe_path(path, private=True, directory=True, missing=True)
    require(not path.exists(), 'output_exists')
    path.mkdir(mode=0o700)
    rs.fsync_dir(path.parent)
    return path


def entry_path(root, name):
    rel = Path(name)
    require(name and not rel.is_absolute() and '..' not in rel.parts, 'unsafe_snapshot_path')
    return root / rel


def seal(source_manifest, start, output):
    source_manifest, output = Path(source_manifest), Path(output)
    dt.date.fromisoformat(start)
    raw = read(source_manifest); data = load(source_manifest)
    require(data.get('status') == 'complete' and data.get('entries'), 'incomplete_manifest')
    require(start <= data.get('cutoff_exclusive', ''), 'seal_after_source_cutoff')
    private_dir(output)
    src_root = source_manifest.parent
    if 'universe' in data:  # schema3 catalog is copied byte-for-byte
        name = data['universe']['path']
        immutable(entry_path(output, name), read(entry_path(src_root, name)))
    entries = []
    for e in data['entries']:
        body = read(entry_path(src_root, e['path']))
        require(digest(body) == e['sha256'], 'snapshot_changed')
        header, *rows = body.decode().splitlines(keepends=True)
        kept = [r for r in rows if r[:10] < start]
        require(kept, 'empty_sealed_entry')
        sealed = (header + ''.join(kept)).encode()
        target = entry_path(output, e['path'])
        for d in reversed(target.relative_to(output).parents[:-1]):
            if not (output / d).exists(): private_dir(output / d)
        immutable(target, sealed)
        entries.append(dict(e, sha256=digest(sealed), rows=len(kept), last=kept[-1][:10]))
    manifest = dict(data, cutoff_exclusive=start, entries=entries, sealed_from_sha256=digest(raw))
    immutable(output / 'manifest.json', json.dumps(manifest, indent=2).encode())
    return output / 'manifest.json'


def bars_after(manifest, start):
    """Distinct dated bars >= start per market in a verified snapshot."""
    data = load(manifest); seen = {'US': set(), 'KR': set()}
    for e in data['entries']:
        body = read(entry_path(manifest.parent, e['path']))
        require(digest(body) == e['sha256'], 'snapshot_changed')
        seen[e['market']].update(r[:10] for r in body.decode().splitlines()[1:] if r[:10] >= start)
    return {m: len(v) for m, v in seen.items()}


def ledger_events(ledger):
    if not ledger.exists(): return []
    return [rs.decode_json(line) for line in read(ledger).splitlines() if line]


def ledger_append(ledger, event):
    rs.safe_path(ledger, private=True, missing=True)
    fd = os.open(ledger, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'ab') as f:
        f.write(encode(event)); f.flush(); os.fsync(f.fileno())


def open_holdout(registry, set_id, manifest, binary, output, ledger, *, run=subprocess.run,
                 min_bars=MIN_BARS, max_openings=MAX_OPENINGS):
    manifest, binary, output, ledger = map(Path, (manifest, binary, output, ledger))
    with rs.Runner(registry, set_id) as runner:
        status = runner.verify(); plan = runner.plan
        require(plan['holdout_status'] == 'sealed', 'not_sealed')
        require(status['state'] == 'completed' and status['conclusion'] == 'accept', 'not_holdout_eligible')
        start = plan['holdout_start']
        require(digest(rs.safe_path(binary).read_bytes()) == plan['binary_sha256'], 'binary_changed')
        bars = bars_after(manifest, start)
        if min(bars.values()) < min_bars:
            return dict(state='holdout_pending', set_id=set_id, bars=bars)
        events = ledger_events(ledger)
        require(not any(e['set_id'] == set_id for e in events), 'holdout_already_opened')
        require(sum(e['event'] == 'open' and e['holdout_start'] == start for e in events) < max_openings,
                'holdout_epoch_exhausted')
        selected = load(runner.folder / 'selection.json')['selected_run_id']
        candidate = next(c for c in runner.candidates() if c['run_id'] == selected)
        rid = selected + '__holdout'
        ledger_append(ledger, dict(event='open', set_id=set_id, holdout_start=start, run_id=rid,
                                   manifest_sha256=digest(read(manifest)), time=dt.datetime.now(dt.timezone.utc).isoformat()))
        private_dir(output)
        strategy = output / (rid + '.toml'); immutable(strategy, runner.strategy_bytes(candidate, rid))
        engine_out = output / 'engine'
        done = run([str(binary), 'run', str(strategy), '--data-manifest', str(manifest),
                    '--output-dir', str(engine_out), '--holdout-start', start],
                   capture_output=True, timeout=600)
        require(done.returncode == 0, 'holdout_run_failed')
        row = next((r for r in load(engine_out / 'index.json') if r['id'] == rid), None)
        require(row is not None and row.get('status') == 'ok', 'holdout_result_missing')
        evaluation = rs.contract().evaluate_holdout(row)
        record = dict(schema_version=1, set_id=set_id, holdout_start=start, selected_run_id=selected,
                      run_id=rid, bars=bars, evaluation=evaluation, result=row,
                      manifest_sha256=digest(read(manifest)), binary_sha256=plan['binary_sha256'])
        raw = encode(record); immutable(output / 'holdout.json', raw)
        public = dict(schema_version=1, set_id=set_id, holdout_start=start,
                      conclusion=evaluation['conclusion'], criterion=evaluation['criterion'], private_sha256=digest(raw))
        immutable(output / 'holdout.public.json', encode(public))
        ledger_append(ledger, dict(event='result', set_id=set_id, holdout_start=start,
                                   conclusion=evaluation['conclusion'], private_sha256=digest(raw)))
        return dict(state='holdout_opened', set_id=set_id, conclusion=evaluation['conclusion'])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('seal'); s.add_argument('--source-manifest', required=True)
    s.add_argument('--start', required=True); s.add_argument('--output', required=True)
    o = sub.add_parser('open')
    for name in ('registry', 'set-id', 'manifest', 'binary', 'output', 'ledger'):
        o.add_argument('--' + name, required=True)
    a = p.parse_args(argv)
    try:
        if a.command == 'seal':
            seal(a.source_manifest, a.start, a.output); print('sealed input written')
        else:
            print(json.dumps(open_holdout(a.registry, a.set_id, a.manifest, a.binary, a.output, a.ledger)))
    except (Exception, KeyboardInterrupt) as e:
        # Controlled codes only: never interpolate paths, engine logs or metrics.
        print(json.dumps({'state': 'blocked', 'code': str(e) if type(e) is Blocked else None}))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
