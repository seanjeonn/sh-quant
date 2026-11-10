"""Offline lifecycle tests for #30. All fixtures are synthetic, never market data."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


class InitialTests(unittest.TestCase):
    def test_help_is_real_cli(self):
        p = subprocess.run([sys.executable, str(ROOT / 'tools/research_set.py'), '--help'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        for command in ('init', 'descriptor', 'checkpoint', 'step', 'verify', 'status'):
            self.assertIn(command, p.stdout)


import datetime as dt
import hashlib
import shutil
from zoneinfo import ZoneInfo
import research_set as r


def write(path, value):
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    path.chmod(0o600)


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL).decode().strip()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve(); self.base.chmod(0o700)
        self.repo = self.base / 'repo'; self.repo.mkdir()
        git(self.repo, 'init', '-b', 'research/synthetic')
        git(self.repo, 'config', 'user.name', 'Synthetic')
        git(self.repo, 'config', 'user.email', 'synthetic@example.invalid')
        (self.repo / 'src').mkdir()
        (self.repo / 'src/main.rs').write_text('// synthetic code')
        (self.repo / 'Cargo.lock').write_text('# synthetic lock')
        git(self.repo, 'add', 'src', 'Cargo.lock'); git(self.repo, 'commit', '-m', 'synthetic')
        self.remote = self.base / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        git(self.repo, 'remote', 'add', 'origin', str(self.remote))
        self.binary = self.base / 'engine'
        shutil.copyfile(Path(sys.executable).resolve(), self.binary); self.binary.chmod(0o700)
        self.manifest = self.base / 'manifest.json'
        self.csv = self.base / 'US_X.csv'; write(self.csv, b'synthetic data')
        write(self.manifest, {'schema_version': 2, 'status': 'complete', 'entries': [
            {'path': self.csv.name, 'sha256': hashlib.sha256(self.csv.read_bytes()).hexdigest()}]})
        from test_research_contract import plan
        self.plan = plan()
        day = dt.datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
        old = self.plan['set_id']; self.plan['set_id'] = day + '_synthetic'
        for c in [self.plan['baseline'], *self.plan['variants']]: c['run_id'] = c['run_id'].replace(old, self.plan['set_id'])
        self.plan.update(engine_commit=git(self.repo, 'rev-parse', 'HEAD'),
            cargo_lock_sha256=hashlib.sha256((self.repo / 'Cargo.lock').read_bytes()).hexdigest(),
            binary_sha256=hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            data_manifest_sha256=hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        self.planpath = self.base / 'plan.json'; write(self.planpath, self.plan)
        self.registry = self.base / 'registry'

    def init(self):
        return r.initialize(self.registry, self.planpath, self.repo, self.binary, self.manifest)


    def checkpoint(self, runner, kind):
        descriptor = runner.descriptor(kind)
        folder = self.repo / 'research' / self.plan['set_id']; folder.mkdir(parents=True, exist_ok=True)
        path = folder / (kind + '.json'); path.write_bytes(descriptor)
        rel = str(path.relative_to(self.repo))
        git(self.repo, 'add', rel); git(self.repo, 'commit', '-m', kind)
        commit = git(self.repo, 'rev-parse', 'HEAD')
        git(self.repo, 'push', 'origin', 'HEAD:refs/heads/research/synthetic')
        return runner.checkpoint(kind, commit, 'origin', 'research/synthetic', rel)


class CheckpointTests(Fixture):
    def test_exact_blob_remote_and_stage_gates(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id']) as runner:
            data = runner.descriptor('plan')
            obj = json.loads(data)
            self.assertEqual(obj['private_sha256'], hashlib.sha256(self.planpath.read_bytes()).hexdigest())
            for secret in (str(self.base), 'Synthetic hypothesis', 'close >', 'sharpe', 'parameters'):
                self.assertNotIn(secret, data.decode())
            with self.assertRaises(r.Blocked): runner.descriptor('selection')
            with self.assertRaises(r.Blocked): runner.checkpoint('plan', self.plan['engine_commit'], 'origin', 'research/synthetic', 'Cargo.lock')
            self.checkpoint(runner, 'plan')
            self.assertEqual(runner.status()['state'], 'ready_trial')
            # Checkpoint artifacts are immutable and a wrong descriptor cannot unlock a phase.
            self.assertEqual(runner.descriptor('plan'), data)
            with self.assertRaises(r.Blocked): runner.checkpoint('selection', self.plan['engine_commit'], 'origin', 'main', '../secret')

    def test_local_blob_without_remote_is_not_checkpoint(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id']) as runner:
            (self.repo / 'plan.json').write_bytes(runner.descriptor('plan'))
            git(self.repo, 'add', 'plan.json'); git(self.repo, 'commit', '-m', 'not pushed')
            commit = git(self.repo, 'rev-parse', 'HEAD')
            with self.assertRaises(r.Blocked): runner.checkpoint('plan', commit, 'origin', 'research/synthetic', 'plan.json')
            self.assertEqual(runner.status()['state'], 'await_plan_checkpoint')


MOCK_ENGINE = r'''
import json, os, pathlib, sys
args = sys.argv[1:]
p = pathlib.Path(args[1]); rid = p.stem
out = pathlib.Path(args[5]); out.mkdir(mode=0o700, exist_ok=True)
metrics = {'sharpe': 1.0, 'cagr': .1, 'mdd': -.2, 'excess_cagr': .01}
row = {'id': rid, 'status': 'ok', 'markets': {m: {s: metrics for s in ('is','oos')} for m in ('US','KR')}}
for name, obj in [(rid+'.json', {'id': rid, 'curves': {'US': [], 'KR': []}}), ('index.json', [row])]:
    path = out / name
    with open(path, 'w') as f: json.dump(obj, f); f.flush(); os.fsync(f.fileno())
    path.chmod(0o600)
'''


class EngineFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.mock = self.base / 'synthetic_engine.py'; write(self.mock, MOCK_ENGINE.encode())

    def launch(self, args, **kwargs):
        return subprocess.Popen([sys.executable, str(self.mock), *args[1:]], **kwargs)


class LifecycleTests(EngineFixture):
    def test_bounded_steps_full_lifecycle_and_verify(self):
        self.init()
        for number in range(3):
            with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
                if number == 0: self.checkpoint(runner, 'plan')
                status = runner.step()
                self.assertEqual(status['attempt_count'], number + 1)
                self.assertFalse(runner.has('selection'))
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.assertEqual(runner.step()['state'], 'await_selection_checkpoint')
            self.assertEqual(runner.step()['state'], 'await_selection_checkpoint')
            self.assertFalse(runner.has('evaluation'))
            self.checkpoint(runner, 'selection')
            self.assertEqual(runner.step()['state'], 'ready_finalize')
            self.assertEqual(runner.step()['state'], 'completed')
            self.assertEqual(runner.verify()['conclusion'], 'accept')
            self.assertEqual(runner.step()['attempt_count'], 3)
            self.assertTrue((runner.folder / 'report.json').is_file())
            self.assertTrue((runner.folder / 'lessons.json').is_file())
        self.assertEqual(self.init()['state'], 'completed')
        with r.Runner(self.registry, self.plan['set_id']) as runner:
            self.assertEqual(runner.verify()['state'], 'completed')
            first = next(e for e in runner.events if e['event'] == 'start')
            detail = runner.folder / first['result_dir'] / (first['run_id'] + '.json')
            write(detail, {'id': first['run_id'], 'tampered': True})
            with self.assertRaises(r.Blocked): runner.verify()

    def test_successful_committed_result_without_end_is_recovered_not_rerun(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan'); runner.step()
            events = runner.events
            # Model SIGKILL immediately after engine commit but before end-event fsync.
            ends = [e for e in events if e['event'] == 'end']; self.assertEqual(len(ends), 1)
            path = runner.folder / 'events.jsonl'; lines = path.read_bytes().splitlines(keepends=True)
            path.write_bytes(b''.join(lines[:-1]))
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            runner.step()
            self.assertEqual(runner.status()['attempt_count'], 1)
            self.assertEqual(len(runner.successes()), 1)

    def test_missing_entry_and_forged_complete_rejected(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan'); runner.step()
            start = next(e for e in runner.events if e['event'] == 'start')
            index = runner.folder / start['result_dir'] / 'index.json'; index.unlink()
            with self.assertRaises(r.Blocked): runner.verify()
        # A valid hash-chain is not enough: completed must recompute every prerequisite.
        with r.registry_lock(self.registry):
            r.Runner.append_raw(self.registry / self.plan['set_id'], {'event':'complete','time':0,'conclusion':'accept'})
        with self.assertRaises(r.Blocked):
            with r.Runner(self.registry, self.plan['set_id']) as runner: runner.verify()


import time
import signal
from unittest import mock


class ProcessTests(EngineFixture):
    def worker(self, script):
        code = ('import sys, subprocess; sys.path.insert(0, ' + repr(str(ROOT / 'tools')) + '); '
                'import research_set as r; '
                'launch=lambda a,**kw: subprocess.Popen([sys.executable,' + repr(str(script)) + ',*a[1:]],**kw); '
                '\nwith r.Runner(' + repr(str(self.registry)) + ',' + repr(self.plan['set_id']) + ',launch=launch) as runner: runner.step()')
        return subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait_child(self):
        path = self.registry / self.plan['set_id'] / 'events.jsonl'
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            events = [json.loads(line) for line in path.read_text().splitlines()]
            children = [e for e in events if e['event'] == 'child']
            if children: return children[-1]['pid']
            time.sleep(.02)
        self.fail('synthetic child did not start')

    def test_sigkill_parent_keeps_orphan_lock_and_recovers_without_duplicate(self):
        write(self.mock, ('import time\ntime.sleep(1.2)\n' + MOCK_ENGINE).encode())
        self.init()
        with r.Runner(self.registry, self.plan['set_id']) as runner: self.checkpoint(runner, 'plan')
        parent = self.worker(self.mock)
        self.addCleanup(lambda: parent.poll() is None and parent.kill())
        child_pid = self.wait_child(); parent.kill(); parent.wait(timeout=3)
        with self.assertRaises(r.Blocked):
            with r.Runner(self.registry, self.plan['set_id']): pass
        # Do not signal a PID read from disk. The mock terminates itself.
        time.sleep(1.4)
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            runner.step()
            self.assertEqual(runner.status()['attempt_count'], 1)
            self.assertEqual(len(runner.successes()), 1)

    def test_sigkill_interrupted_attempt_uses_new_repair_id(self):
        write(self.mock, b'import time,os\ntime.sleep(.8)\nos._exit(9)\n')
        self.init()
        with r.Runner(self.registry, self.plan['set_id']) as runner: self.checkpoint(runner, 'plan')
        parent = self.worker(self.mock)
        self.addCleanup(lambda: parent.poll() is None and parent.kill())
        self.wait_child(); parent.kill(); parent.wait(timeout=3); time.sleep(1)
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            runner.step()
            self.assertEqual(runner.ends()[runner.starts()[0]['run_id']]['status'], 'interrupted')
            write(self.mock, MOCK_ENGINE.encode()); runner.step()
            self.assertEqual(runner.status()['attempt_count'], 2)
            self.assertTrue(runner.starts()[-1]['run_id'].endswith('__repair1'))
            self.assertEqual(len(runner.successes()), 1)

    def test_timeout_reaps_owned_child_and_concurrency_rejects(self):
        write(self.mock, b'import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(30)\n')
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan')
            second = self.worker(self.mock); self.assertNotEqual(second.wait(timeout=4), 0)
            before = time.monotonic()
            with mock.patch.object(r, 'TRIAL_TIMEOUT', .15): runner.step()
            self.assertLess(time.monotonic() - before, 4)
            child = next(e for e in runner.events if e['event'] == 'child')
            with self.assertRaises(ProcessLookupError): os.kill(child['pid'], 0)
            self.assertEqual(runner.ends()[child['run_id']]['status'], 'failed')
            self.assertTrue(runner.ends()[child['run_id']]['timeout'])


class SecurityTests(EngineFixture):
    def test_plan_descriptor_cannot_be_recreated_after_trial(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan'); runner.step()
            (runner.folder / 'plan.public.json').unlink()
            with self.assertRaises(r.Blocked): runner.descriptor('plan')

    def test_budget_is_durable_across_restart(self):
        self.plan['budget']['max_attempts'] = 3; self.plan['budget']['max_repairs'] = 0
        write(self.planpath, self.plan)
        write(self.mock, b'import sys\nsys.exit(1)\n')
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan'); runner.step()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            with self.assertRaises(r.Blocked): runner.step()
            self.assertEqual(runner.status()['state'], 'blocked')
            self.assertEqual(runner.status()['attempt_count'], 1)

    def test_private_tamper_code_snapshot_config_and_journal_rejected(self):
        self.init()
        for target in (self.repo / 'src/main.rs', self.csv,
                       self.registry / self.plan['set_id'] / 'config.json',
                       self.registry / self.plan['set_id'] / 'events.jsonl'):
            raw = target.read_bytes(); target.write_bytes(raw + b'corrupt')
            with self.assertRaises((r.Blocked, ValueError)):
                with r.Runner(self.registry, self.plan['set_id']) as runner: runner.verify()
            target.write_bytes(raw)

    def test_snapshot_copies_and_descriptor_provenance_are_preserved(self):
        self.init()
        folder = self.registry / self.plan['set_id']
        self.assertEqual((folder / 'binary.snapshot').read_bytes(), self.binary.read_bytes())
        snapshot = json.loads((folder / 'code.snapshot.json').read_bytes())
        self.assertEqual(bytes.fromhex(snapshot['src/main.rs']), (self.repo / 'src/main.rs').read_bytes())

    def test_wall_budget_blocks_selection_after_restart(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan')
            for _ in range(3): runner.step()
        with r.Runner(self.registry, self.plan['set_id']) as runner:
            with mock.patch.object(r.time, 'time', return_value=runner.starts()[0]['time'] + 7201):
                with self.assertRaises(r.Blocked): runner.step()
            self.assertEqual(runner.status()['state'], 'blocked')

    def test_private_plan_rewrite_cannot_bypass_public_hash_anchor(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id']) as runner:
            self.checkpoint(runner, 'plan')
            folder = runner.folder
            original = runner.events
        changed = dict(self.plan, hypothesis='modified after public checkpoint')
        write(self.planpath, changed); write(folder / 'plan.json', changed)
        config = json.loads((folder / 'config.json').read_bytes())
        config['plan_sha256'] = hashlib.sha256(self.planpath.read_bytes()).hexdigest()
        write(folder / 'config.json', r.encode(config))
        original[0]['config_sha256'] = r.digest(r.encode(config)); original[0]['plan_sha256'] = config['plan_sha256']
        (folder / 'events.jsonl').write_bytes(b'')
        for event in original:
            event.pop('previous', None); r.Runner.append_raw(folder, event)
        with self.assertRaises(r.Blocked):
            with r.Runner(self.registry, self.plan['set_id']) as runner: runner.verify()

    def test_completed_duration_and_logs_are_verified(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan'); runner.step()
            start = runner.starts()[0]; trial, _ = runner.trial_paths(start)
            (trial / 'stderr.log').write_bytes(b'tampered synthetic log')
            with self.assertRaises(r.Blocked): runner.verify()

    def test_timeout_kills_descendant_when_leader_exits_on_term(self):
        write(self.mock, b'''import os,signal,time,pathlib
pid=os.fork()
if pid==0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)
else:
    pathlib.Path(__file__).with_suffix('.pid').write_text(str(pid))
    time.sleep(30)
''')
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan')
            with mock.patch.object(r, 'TRIAL_TIMEOUT', .3): runner.step()
        pid = int(self.mock.with_suffix('.pid').read_text())
        # A terminated orphan can briefly remain as a zombie on macOS.
        status = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
        alive = status.returncode == 0 and 'Z' not in status.stdout
        if alive: os.kill(pid, signal.SIGKILL)  # synthetic child just created by this test
        self.assertFalse(alive, 'timeout leaked live synthetic grandchild')

    def test_complete_after_blocker_or_outside_wall_budget_rejected(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan')
            for _ in range(4): runner.step()
            self.checkpoint(runner, 'selection'); runner.step()
            original = (runner.folder / 'events.jsonl').read_bytes()
            for reason in ('blocked', 'late'):
                (runner.folder / 'events.jsonl').write_bytes(original)
                runner.events = runner.read_events()
                for name, value in [('report', runner.report_value()), ('lessons', runner.lessons_value())]:
                    write(runner.folder / (name + '.json'), r.encode(value))
                if reason == 'blocked': runner.append({'event': 'blocked', 'reason': 'synthetic'})
                event = {'event': 'complete', 'conclusion': 'accept',
                         'report_sha256': r.digest((runner.folder / 'report.json').read_bytes()),
                         'lessons_sha256': r.digest((runner.folder / 'lessons.json').read_bytes()),
                         'time': runner.starts()[0]['time'] + 7201 if reason == 'late' else time.time()}
                r.Runner.append_raw(runner.folder, event); runner.events = runner.read_events()
                with self.subTest(reason=reason), self.assertRaises(r.Blocked): runner.verify()

    def test_git_external_diff_is_never_executed(self):
        marker = self.base / 'unsafe_external_diff_ran'
        helper = self.base / 'external-diff'
        write(helper, ('#!/bin/sh\ntouch ' + str(marker) + '\nexit 0\n').encode()); helper.chmod(0o700)
        git(self.repo, 'config', 'diff.external', str(helper))
        (self.repo / 'src/main.rs').write_text('// changed synthetic engine')
        with self.assertRaises(r.Blocked): self.init()
        self.assertFalse(marker.exists(), 'Git executed an external shell helper')

    def test_untracked_code_input_is_frozen(self):
        (self.repo / 'tools').mkdir()
        helper = self.repo / 'tools/helper.py'; helper.write_text('# synthetic helper')
        self.init(); helper.write_text('# changed synthetic helper')
        with self.assertRaises(r.Blocked):
            with r.Runner(self.registry, self.plan['set_id']) as runner: runner.verify()

    def test_strategy_hash_and_command_cannot_override_frozen_signal(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan'); runner.step()
            start = runner.starts()[0]; trial, _ = runner.trial_paths(start)
            strategy = trial / (start['run_id'] + '.toml')
            strategy.write_bytes(strategy.read_bytes().replace(b'close > 1', b'close > 9'))
            events = runner.events
            for e in events:
                if e['event'] == 'start': e['strategy_sha256'] = r.digest(strategy.read_bytes())
            (runner.folder / 'events.jsonl').write_bytes(b'')
            for e in events:
                e.pop('previous', None); r.Runner.append_raw(runner.folder, e)
        with self.assertRaises(r.Blocked):
            with r.Runner(self.registry, self.plan['set_id']) as runner: runner.verify()

    def test_repaired_baseline_full_lifecycle_uses_candidate_alias(self):
        write(self.mock, b'import sys\nsys.exit(1)\n')
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan'); runner.step()
            write(self.mock, MOCK_ENGINE.encode())
            for _ in range(3): runner.step()
            runner.step(); self.checkpoint(runner, 'selection'); runner.step(); runner.step()
            self.assertEqual(runner.verify()['state'], 'completed')
            self.assertEqual(runner.verify()['attempt_count'], 4)
            selected = json.loads((runner.folder / 'selection.json').read_bytes())
            self.assertEqual(selected['selected_run_id'], self.plan['baseline']['run_id'])

    def test_ref_signal_and_unknown_cli_parameters_rejected(self):
        self.plan['variants'][0]['signal'] = 'ref("outside")'
        write(self.planpath, self.plan)
        with self.assertRaises(r.Blocked): self.init()
        self.plan['variants'][0]['signal'] = '1'
        self.plan['variants'][0]['parameters'] = {'command': ['sh', '-c', 'no']}
        write(self.planpath, self.plan)
        with self.assertRaises(r.Blocked): self.init()


class CliTests(Fixture):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'tools/research_set.py'), *args], capture_output=True, text=True)

    def test_init_status_step_verify_and_safe_failure(self):
        p = self.cli('init', '--registry', str(self.registry), '--plan', str(self.planpath),
                     '--repo', str(self.repo), '--binary', str(self.binary), '--manifest', str(self.manifest))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)['state'], 'await_plan_checkpoint')
        for command in ('status', 'step', 'verify'):
            p = self.cli(command, '--registry', str(self.registry), '--set-id', self.plan['set_id'])
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)['attempt_count'], 0)
        p = self.cli('descriptor', '--registry', str(self.registry), '--set-id', self.plan['set_id'], '--kind', 'plan')
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout)['kind'], 'plan')
        write(self.planpath, {'secret': 'SENSITIVE_SYNTHETIC'})
        p = self.cli('step', '--registry', str(self.registry), '--set-id', self.plan['set_id'])
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout)['state'], 'blocked')
        self.assertNotIn('SENSITIVE_SYNTHETIC', p.stdout + p.stderr)
        self.assertNotIn(str(self.base), p.stdout + p.stderr)


class InitTests(Fixture):
    def test_next_day_init_resumes_original_id_without_canary(self):
        self.init()
        tomorrow = dt.datetime.now(ZoneInfo('Asia/Seoul')) + dt.timedelta(days=1)
        with mock.patch.object(r.dt, 'datetime') as clock:
            clock.now.return_value = tomorrow
            self.assertEqual(self.init()['state'], 'await_plan_checkpoint')
            with self.assertRaises(r.Blocked):
                r.initialize(self.base / 'new_registry', self.planpath, self.repo, self.binary, self.manifest)

    def test_private_init_is_idempotent_and_gated(self):
        self.init(); self.init()
        with r.Runner(self.registry, self.plan['set_id']) as runner:
            self.assertEqual(runner.status()['state'], 'await_plan_checkpoint')
            self.assertEqual(runner.step()['state'], 'await_plan_checkpoint')
            self.assertEqual(runner.status()['attempt_count'], 0)
        self.assertEqual(self.registry.stat().st_mode & 0o777, 0o700)
        for p in self.registry.rglob('*'):
            self.assertEqual(p.stat().st_mode & 0o777, 0o700 if p.is_dir() else 0o600)

    def test_reject_changed_plan_and_second_set(self):
        self.init()
        self.plan['hypothesis'] += ' changed'; write(self.planpath, self.plan)
        with self.assertRaises(r.Blocked): self.init()
        self.plan['set_id'] = self.plan['set_id'].replace('_synthetic', '_other')
        write(self.planpath, self.plan)
        with self.assertRaises(r.Blocked): self.init()

    def test_reject_unsafe_private_inputs(self):
        self.planpath.chmod(0o644)
        with self.assertRaises(r.Blocked): self.init()
        self.planpath.chmod(0o600)
        alias = self.base / 'alias'; os.link(self.planpath, alias)
        with self.assertRaises(r.Blocked): self.init()
        alias.unlink(); alias.symlink_to(self.planpath)
        with self.assertRaises(r.Blocked): r.initialize(self.registry, alias, self.repo, self.binary, self.manifest)


if __name__ == '__main__':
    unittest.main()
