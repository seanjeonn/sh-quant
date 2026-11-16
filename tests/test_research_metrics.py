import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import research_metrics as m  # noqa: E402
import research_set as r  # noqa: E402
from test_research_set import EngineFixture, write  # noqa: E402


class SetMetricsTests(EngineFixture):
    def test_completed_lifecycle_phases_and_trial_usage(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan')
            for _ in range(4): runner.step()
            self.checkpoint(runner, 'selection'); runner.step(); runner.step()
            self.assertEqual(runner.verify()['state'], 'completed')
            folder = runner.folder
        before = {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        out = m.set_metrics(folder)
        self.assertEqual(before, {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()})  # read-only
        self.assertEqual((out['state'], out['attempts'], len(out['trials'])), ('completed', 3, 3))
        self.assertEqual([t['role'] for t in out['trials']], ['baseline', 'variant', 'variant'])
        for key, value in out['phases_seconds'].items():
            self.assertIsNotNone(value, key); self.assertGreaterEqual(value, 0, key)
        phases = out['phases_seconds']
        self.assertLessEqual(phases['trials'], phases['total'])
        self.assertGreater(out['trial_cpu_seconds_sum'], 0)
        self.assertGreater(out['trial_max_rss_bytes'], 0)
        # Only durations/counts/usage: no market metrics, commands or paths.
        text = json.dumps(out)
        for banned in ('sharpe', 'cagr', 'mdd', 'command', str(self.base)):
            self.assertNotIn(banned, text)

    def test_open_set_without_trials(self):
        self.init()
        out = m.set_metrics(self.registry / self.plan['set_id'])
        self.assertEqual((out['state'], out['attempts'], out['trial_cpu_seconds_sum']), ('open', 0, None))
        self.assertIsNone(out['phases_seconds']['trials'])


class DayMetricsTests(EngineFixture):
    def make_day(self):
        day = self.base / 'private' / '2026-11-16'; day.mkdir(parents=True, mode=0o700); day.parent.chmod(0o700)
        write(day / 'ledger.json', {'status': 'completed', 'launches': 2, 'acquisition_attempts': 1,
                                    'started_epoch': 1000.0, 'updated_epoch': 4600.0})
        for i, (kind, start, end, rc, timeout) in enumerate([
                ('acquisition', 1000, 1300, 0, False), ('daily', 1300, 2900, 0, False),
                ('continue', 3000, 3600, 1, True), ('continue', 3700, None, None, None)]):
            inv = day / ('invocation-%02d' % i); inv.mkdir(mode=0o700)
            write(inv / 'start.json', {'kind': kind, 'started_at': start, 'command': ['secret-arg']})
            if end is not None:
                write(inv / 'end.json', {'ended_at': end, 'exit_code': rc, 'timed_out': timeout})
        return day

    def test_invocation_rollup(self):
        out = m.day_metrics(self.make_day())
        self.assertEqual((out['status'], out['launches'], out['ledger_span_seconds']), ('completed', 2, 3600.0))
        inv = out['invocations']
        self.assertEqual(inv['acquisition']['seconds_sum'], 300)
        self.assertEqual(inv['daily']['seconds_max'], 1600)
        self.assertEqual({k: inv['continue'][k] for k in ('count', 'open', 'failed', 'timed_out', 'seconds_sum')},
                         {'count': 2, 'open': 1, 'failed': 1, 'timed_out': 1, 'seconds_sum': 600})
        self.assertIsNone(out['llm_tokens'])
        self.assertNotIn('secret-arg', json.dumps(out))

    def test_cli_rejects_unsafe_permissions(self):
        day = self.make_day(); (day / 'ledger.json').chmod(0o644)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(['--day', str(day)]), 2)
        self.assertIn('unsafe_permissions', err.getvalue())
