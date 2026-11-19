"""#109 sealed forward holdout. Synthetic fixtures only, never market data."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from test_research_set import EngineFixture, write
import holdout as h
import research_set as r

ROOT = Path(__file__).resolve().parents[1]
START = '2026-12-01'


def csv(days, first='2026-06-01'):
    d0 = dt.date.fromisoformat(first)
    rows = ''.join(f'{d0 + dt.timedelta(i)},1,1,1,1,1\n' for i in range(days))
    return ('date,open,high,low,close,volume\n' + rows).encode()


def snapshot(folder, days, cutoff='2027-12-31'):
    folder.mkdir(mode=0o700)
    entries = []
    for market in ('US', 'KR'):
        body = csv(days); name = market + '_X.csv'; write(folder / name, body)
        lines = body.decode().splitlines()
        entries.append(dict(market=market, ticker='X', path=name, sha256=hashlib.sha256(body).hexdigest(),
                            rows=len(lines) - 1, first=lines[1][:10], last=lines[-1][:10]))
    write(folder / 'manifest.json', dict(schema_version=2, status='complete', cutoff_exclusive=cutoff, entries=entries))
    return folder / 'manifest.json'


class SealTests(EngineFixture):
    def test_seal_keeps_only_bars_before_start_and_leaves_source(self):
        source = snapshot(self.base / 'full', 400)
        before = {p.name: p.read_bytes() for p in source.parent.iterdir()}
        sealed = h.seal(source, START, self.base / 'sealed')
        data = json.loads(sealed.read_bytes())
        self.assertEqual(data['cutoff_exclusive'], START)
        self.assertEqual(data['sealed_from_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        for e in data['entries']:
            body = (sealed.parent / e['path']).read_bytes()
            dates = [line[:10] for line in body.decode().splitlines()[1:]]
            self.assertTrue(dates and max(dates) < START)
            self.assertEqual((e['rows'], e['last'], e['sha256']), (len(dates), dates[-1], hashlib.sha256(body).hexdigest()))
        self.assertEqual({p.name: p.read_bytes() for p in source.parent.iterdir()}, before)
        with self.assertRaises(r.Blocked): h.seal(source, START, self.base / 'sealed')
        with self.assertRaises(r.Blocked): h.seal(source, '2028-01-01', self.base / 'later')


HOLDOUT_ENGINE = r'''
import json, os, pathlib, sys
args = sys.argv[1:]
assert args[-2] == '--holdout-start', args
rid = pathlib.Path(args[1]).stem
out = pathlib.Path(args[5]); out.mkdir(mode=0o700)
m = {'sharpe': SHARPE, 'cagr': .1, 'mdd': -.1, 'excess_cagr': .01}
row = {'id': rid, 'status': 'ok', 'markets': {k: {s: m for s in ('is', 'oos', 'holdout')} for k in ('US', 'KR')}}
path = out / 'index.json'
with open(path, 'w') as f: json.dump([row], f)
path.chmod(0o600)
'''


class OpenTests(EngineFixture):
    def setUp(self):
        super().setUp()
        data = json.loads(self.manifest.read_bytes()); data['cutoff_exclusive'] = START
        write(self.manifest, data)
        self.plan.update(holdout_status='sealed', holdout_start=START,
                         machine_policy=dict(self.plan['machine_policy'], holdout='holdout_forward_v1'),
                         data_manifest_sha256=hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        write(self.planpath, self.plan)
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan')
            for _ in range(4): runner.step()
            self.checkpoint(runner, 'selection'); runner.step(); runner.step()
            self.assertEqual(runner.verify()['conclusion'], 'accept')
        self.ledger = self.base / 'ledger.jsonl'
        self.calls = []

    def engine(self, sharpe):
        script = self.base / ('holdout_engine_' + str(len(self.calls)) + '.py')
        write(script, HOLDOUT_ENGINE.replace('SHARPE', repr(sharpe)).encode())
        def run(argv, **kw):
            self.calls.append(argv)
            return subprocess.run([sys.executable, str(script), *argv[1:]], **kw)
        return run

    def open(self, days, sharpe=0.5, out='out', **kw):
        full = snapshot(self.base / ('full_' + out), days)
        return h.open_holdout(self.registry, self.plan['set_id'], full, self.binary, self.base / out,
                              self.ledger, run=self.engine(sharpe), **kw)

    def test_pending_until_min_bars_without_side_effects(self):
        # 2026-06-01 + 300 days leaves fewer than 126 bars on/after START.
        result = self.open(300)
        self.assertEqual(result['state'], 'holdout_pending')
        self.assertFalse(self.ledger.exists()); self.assertEqual(self.calls, [])

    def test_opens_once_and_records_ledger_before_and_after(self):
        result = self.open(400)
        self.assertEqual((result['state'], result['conclusion']), ('holdout_opened', 'accept'))
        self.assertEqual(self.calls[0][-2:], ['--holdout-start', START])
        events = [json.loads(line) for line in self.ledger.read_bytes().splitlines()]
        self.assertEqual([e['event'] for e in events], ['open', 'result'])
        public = json.loads((self.base / 'out/holdout.public.json').read_bytes())
        self.assertEqual(public['private_sha256'], hashlib.sha256((self.base / 'out/holdout.json').read_bytes()).hexdigest())
        self.assertNotIn('sharpe', json.dumps(public))
        with self.assertRaises(r.Blocked): self.open(400, out='again')
        self.assertEqual(len(self.calls), 1)

    def test_failed_holdout_is_defer_not_retried(self):
        self.assertEqual(self.open(400, sharpe=-0.2)['conclusion'], 'defer')
        with self.assertRaises(r.Blocked): self.open(400, out='again')

    def test_epoch_limit(self):
        for n in range(3):
            h.ledger_append(self.ledger, dict(event='open', set_id='other' + str(n), holdout_start=START))
        with self.assertRaises(r.Blocked): self.open(400)
        self.assertEqual(self.calls, [])

    def test_cli_suppresses_details(self):
        p = subprocess.run([sys.executable, str(ROOT / 'tools/holdout.py'), 'open', '--registry', str(self.registry),
                            '--set-id', 'bad', '--manifest', '/x', '--binary', '/x', '--output', '/x', '--ledger', '/x'],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout), {'state': 'blocked', 'code': 'invalid_set_id'})
        self.assertNotIn(str(self.base), p.stdout + p.stderr)
