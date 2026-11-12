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
        self.plan['next_experiment'] = {
            'hypothesis': 'A separately preregistered longer signal window may reduce synthetic turnover.',
            'reason': 'Compare an untouched later window because the current synthetic OOS is already exposed.'}
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

    def test_forged_hash_chain_cannot_publish_local_checkpoint(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id']) as runner:
            descriptor = runner.descriptor('plan')
            # An ancestor exists remotely, but the descriptor's descendant is unpublished.
            git(self.repo, 'push', 'origin', 'HEAD:refs/heads/research/synthetic')
            (self.repo / 'plan.json').write_bytes(descriptor)
            git(self.repo, 'add', 'plan.json'); git(self.repo, 'commit', '-m', 'unpublished descriptor')
            commit = git(self.repo, 'rev-parse', 'HEAD')
            evidence = dict(event='checkpoint', kind='plan', commit=commit, remote='origin',
                            branch='research/synthetic', path='plan.json', descriptor_sha256=r.digest(descriptor))
            with self.assertRaises(r.Blocked): runner.check_git_checkpoint(evidence)
            original = (runner.folder / 'events.jsonl').read_bytes()
            for overrides in ({}, {'remote': 'NOT_ORIGIN'}, {'branch': 'main'}):
                with self.subTest(overrides=overrides):
                    (runner.folder / 'events.jsonl').write_bytes(original)
                    r.Runner.append_raw(runner.folder, dict(evidence, **overrides))
                    runner.events = runner.read_events()
                    with self.assertRaises(r.Blocked): runner.verify()

    def test_verify_blocks_when_checkpoint_remote_is_unavailable(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id']) as runner:
            self.checkpoint(runner, 'plan')
            self.remote.rename(self.base / 'unavailable.git')
            with self.assertRaises(r.Blocked): runner.verify()

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
    def test_private_lessons_derive_each_candidate_and_use_preregistered_next_experiment(self):
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan')
            for _ in range(4): runner.step()
            self.checkpoint(runner, 'selection'); runner.step()
            lessons = runner.lessons_value(); report = runner.report_value()
            self.assertEqual(lessons['next_experiment'], self.plan['next_experiment'])
            self.assertEqual(report['next_experiment'], self.plan['next_experiment'])
            selection = runner.selection_value()
            self.assertEqual(len(lessons['candidates']), 3)
            for item, row in zip(lessons['candidates'], runner.successes()):
                self.assertEqual(item['candidate_id'], row['id'])
                self.assertEqual(item['run_id'], row['id'])
                self.assertEqual(item['selected'], row['id'] == selection['selected_run_id'])
                ranking = next(v for v in selection['ranking'] if v['run_id'] == row['id'])
                self.assertEqual(item['is_means'], {k:v for k,v in ranking.items() if k != 'run_id'})
                for market in ('US', 'KR'):
                    self.assertEqual(item['metrics_is'][market], row['markets'][market]['is'])
                    self.assertEqual(item['metrics_oos'][market], row['markets'][market]['oos'])
                    self.assertEqual(item['oos_observations'][market]['sharpe_vs_is'], 'equal')
                    self.assertTrue(item['oos_observations'][market]['excess_cagr_nonnegative'])
            self.assertEqual(lessons['evaluation'], runner.evaluation_value())
            runner.step()
            self.assertEqual(runner.verify()['state'], 'completed')

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
    @contextlib.contextmanager
    def wait_runner(self, timeout=8):
        """Wait for actual worker lock release, never retry recovery itself."""
        deadline = time.monotonic() + timeout
        with contextlib.ExitStack() as stack:
            while True:
                try:
                    runner = stack.enter_context(r.Runner(
                        self.registry, self.plan['set_id'], launch=self.launch))
                except r.Blocked as error:
                    remaining = deadline - time.monotonic()
                    if str(error) != 'worker_busy' or remaining <= 0:
                        raise
                    time.sleep(min(.02, remaining))
                else:
                    break
            yield runner

    def worker(self, script, timeout=None):
        code = ('import sys, subprocess; sys.path.insert(0, ' + repr(str(ROOT / 'tools')) + '); '
                'import research_set as r; '
                + (('r.TRIAL_TIMEOUT=' + repr(timeout) + '; ') if timeout is not None else '') +
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
        # Delay beyond the former 1.4s wait to reproduce slow worker release (#47).
        write(self.mock, ('import time\ntime.sleep(3)\n' + MOCK_ENGINE).encode())
        self.init()
        with r.Runner(self.registry, self.plan['set_id']) as runner: self.checkpoint(runner, 'plan')
        parent = self.worker(self.mock)
        self.addCleanup(lambda: parent.poll() is None and parent.kill())
        child_pid = self.wait_child(); parent.kill(); parent.wait(timeout=3)
        with self.assertRaisesRegex(r.Blocked, '^worker_busy$'):
            with r.Runner(self.registry, self.plan['set_id']): pass
        # Do not signal a PID read from disk. Observe the worker releasing its lock.
        with self.wait_runner() as runner:
            runner.step()
            self.assertEqual(runner.status()['attempt_count'], 1)
            self.assertEqual(len(runner.successes()), 1)

    def test_sigkill_interrupted_attempt_uses_new_repair_id(self):
        # Delay beyond the former 1s wait, including failed-engine recovery.
        write(self.mock, b'import time,os\ntime.sleep(3)\nos._exit(9)\n')
        self.init()
        with r.Runner(self.registry, self.plan['set_id']) as runner: self.checkpoint(runner, 'plan')
        parent = self.worker(self.mock)
        self.addCleanup(lambda: parent.poll() is None and parent.kill())
        self.wait_child(); parent.kill(); parent.wait(timeout=3)
        with self.assertRaisesRegex(r.Blocked, '^worker_busy$'):
            with r.Runner(self.registry, self.plan['set_id']): pass
        with self.wait_runner() as runner:
            runner.step()
            self.assertEqual(runner.ends()[runner.starts()[0]['run_id']]['status'], 'interrupted')
            write(self.mock, MOCK_ENGINE.encode()); runner.step()
            self.assertEqual(runner.status()['attempt_count'], 2)
            self.assertTrue(runner.starts()[-1]['run_id'].endswith('__repair1'))
            self.assertEqual(len(runner.successes()), 1)

    def test_normal_exit_cleans_term_ignoring_descendant_before_log_commit(self):
        write(self.mock, b'''import os,signal,time,pathlib
pid=os.fork()
if pid==0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pathlib.Path(__file__).with_suffix('.pid').write_text(str(os.getpid()))
    while True:
        os.write(1,b'descendant log write\\n')
        time.sleep(.02)
else:
    while not pathlib.Path(__file__).with_suffix('.pid').exists(): time.sleep(.01)
    os._exit(7)
''')
        self.init()
        try:
            with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
                self.checkpoint(runner, 'plan'); runner.step()
                end = runner.ends()[runner.starts()[0]['run_id']]
                self.assertEqual(end['exit_code'], 7)
                trial, _ = runner.trial_paths(runner.starts()[0])
                before = (trial / 'stdout.log').read_bytes()
                time.sleep(.15)
                self.assertEqual((trial / 'stdout.log').read_bytes(), before, 'descendant mutated committed log')
            with r.Runner(self.registry, self.plan['set_id']) as runner: runner.verify()
            pid = int(self.mock.with_suffix('.pid').read_text())
            status = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
            self.assertFalse(status.returncode == 0 and 'Z' not in status.stdout, 'live descendant')
        finally:
            path = self.mock.with_suffix('.pid')
            if path.exists():
                try: os.kill(int(path.read_text()), signal.SIGKILL)
                except ProcessLookupError: pass

    def assert_orphan_group_releases_lock(self, leader_sleep, timeout):
        write(self.mock, ('''import os,signal,time,pathlib
pid=os.fork()
if pid==0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pathlib.Path(__file__).with_suffix('.pid').write_text(str(os.getpid()))
    while True:
        os.write(1,b'orphan log write\\n')
        time.sleep(.02)
else:
    time.sleep(''' + str(leader_sleep) + ')\n').encode())
        self.init()
        with r.Runner(self.registry, self.plan['set_id']) as runner: self.checkpoint(runner, 'plan')
        parent = self.worker(self.mock, timeout=timeout)
        try:
            self.wait_child()
            deadline = time.monotonic() + 3
            while not self.mock.with_suffix('.pid').exists() and time.monotonic() < deadline: time.sleep(.01)
            self.assertTrue(self.mock.with_suffix('.pid').exists())
            parent.kill(); parent.wait(timeout=3)
            with self.assertRaises(r.Blocked):
                with r.Runner(self.registry, self.plan['set_id']): pass
            deadline = time.monotonic() + 4
            while True:
                try:
                    with r.Runner(self.registry, self.plan['set_id']) as runner:
                        runner.step()
                        trial, _ = runner.trial_paths(runner.starts()[0])
                        before = (trial / 'stdout.log').read_bytes()
                        time.sleep(.1)
                        self.assertEqual(before, (trial / 'stdout.log').read_bytes())
                        self.assertEqual(runner.verify()['attempt_count'], 1)
                    break
                except r.Blocked as error:
                    if str(error) != 'worker_busy' or time.monotonic() >= deadline: raise
                    time.sleep(.03)
            pid = int(self.mock.with_suffix('.pid').read_text())
            status = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
            self.assertFalse(status.returncode == 0 and 'Z' not in status.stdout)
        finally:
            if parent.poll() is None: parent.kill(); parent.wait(timeout=3)
            path = self.mock.with_suffix('.pid')
            if path.exists():
                try: os.kill(int(path.read_text()), signal.SIGKILL)
                except ProcessLookupError: pass

    def test_sigkill_parent_normal_engine_exit_cleans_descendant(self):
        self.assert_orphan_group_releases_lock(leader_sleep=.8, timeout=3)

    def test_sigkill_parent_supervisor_enforces_timeout_and_cleans_descendant(self):
        self.assert_orphan_group_releases_lock(leader_sleep=30, timeout=.8)

    def test_parent_exception_cancels_owned_group_via_control_pipe(self):
        write(self.mock, b'import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(30)\n')
        self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan')
            append = runner.append; supervisor = []
            def interrupt_after_launch(event):
                append(event)
                if event['event'] == 'child':
                    supervisor.append(event['pid'])
                    raise KeyboardInterrupt()
            with mock.patch.object(runner, 'append', side_effect=interrupt_after_launch):
                with self.assertRaises(KeyboardInterrupt): runner.step()
            self.assertEqual(len(supervisor), 1)
            with self.assertRaises(ProcessLookupError): os.kill(supervisor[0], 0)
        with r.Runner(self.registry, self.plan['set_id']) as runner:
            runner.step()
            self.assertEqual(runner.ends()[runner.starts()[0]['run_id']]['status'], 'interrupted')

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

    def test_untracked_root_build_inputs_create_change_delete_block_verify(self):
        self.init()
        for name in ('build.rs', 'Cargo.toml', 'rust-toolchain.toml', 'rust-toolchain'):
            path = self.repo / name
            with self.subTest(name=name):
                path.write_text('// new build input')
                with self.assertRaises(r.Blocked):
                    with r.Runner(self.registry, self.plan['set_id']) as runner: runner.verify()
                path.unlink()
        # Presence and content of initially untracked inputs must also be frozen.
        build = self.repo / 'build.rs'; build.write_text('// original')
        self.registry = self.base / 'registry_with_build'; self.init()
        for contents in ('// modified', None):
            if contents is None: build.unlink()
            else: build.write_text(contents)
            with self.assertRaises(r.Blocked):
                with r.Runner(self.registry, self.plan['set_id']) as runner: runner.verify()

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


class ScopeTests(EngineFixture):
    def scope(self, name='lease', seconds=5.0):
        folder = self.base / name; folder.mkdir(mode=0o700)
        path = folder / 'scope.json'
        write(path, {'schema_version': 1, 'expires_at': time.time() + seconds, 'token': name})
        return (str(path), r.digest(path.read_bytes()))

    def nested(self, mode):
        scope = self.scope(name=mode, seconds=.7 if mode == 'parentdeath' else 5)
        heartbeat = self.base / (mode + '.heartbeat')
        ready = self.base / (mode + '.ready')
        leaf = ('import pathlib,time,signal,os,json; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                'p=pathlib.Path(' + repr(str(heartbeat)) + '); tmp=p.with_suffix(".tmp"); '
                '\nwhile True: tmp.write_text(json.dumps([os.getpid(),time.time()])); tmp.replace(p); time.sleep(.01)')
        inner = ('import sys,subprocess,time,pathlib,os; sys.path.insert(0,' + repr(str(ROOT / 'tools')) + '); '
                 'import research_set as r; '
                 'child=r.OwnedTrial(subprocess.Popen,[sys.executable,"-c",' + repr(leaf) + '],timeout=2); '
                 'pathlib.Path(' + repr(str(ready)) + ').write_text(str(child.pid)); '
                 + ('time.sleep(.12); os._exit(0)' if mode == 'normal' else 'child.wait()'))
        env = dict(os.environ)
        outer_code = ('import sys,subprocess; sys.path.insert(0,' + repr(str(ROOT / 'tools')) + '); '
                      'import research_set as r; '
                      'c=r.OwnedTrial(subprocess.Popen,[sys.executable,"-c",' + repr(inner) + '],'
                      'timeout=2,revoke_scope=True,execution_scope=' + repr(scope) + '); c.wait()')
        parent = None; outer = None
        try:
            if mode == 'parentdeath':
                parent = subprocess.Popen([sys.executable, '-c', outer_code], env=env)
            else:
                outer = r.OwnedTrial(subprocess.Popen, [sys.executable, '-c', inner], timeout=.4,
                                     execution_scope=scope, revoke_scope=True, env=env)
            deadline = time.monotonic() + 2
            while not heartbeat.exists() and time.monotonic() < deadline: time.sleep(.01)
            self.assertTrue(heartbeat.exists(), 'genuine nested OwnedTrial did not launch')
            if mode == 'parentdeath':
                assert parent is not None
                parent.kill(); parent.wait(timeout=2)
            else:
                assert outer is not None
                if mode == 'explicit': outer.stop()
                elif mode == 'flag': r.revoke_scope(scope); outer.wait()
                else: outer.wait()
            time.sleep(.45 if mode != 'parentdeath' else .95)
            before = heartbeat.read_bytes(); time.sleep(.12)
            self.assertEqual(heartbeat.read_bytes(), before, 'nested owned group survived cancellation/deadline')
            for pid in (int(ready.read_text()), json.loads(before)[0]):
                status = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
                self.assertFalse(status.returncode == 0 and 'Z' not in status.stdout, 'live nested process')
            self.assertTrue((Path(scope[0]).parent / 'cancelled').exists())
        finally:
            # No PID from a file is ever signalled. All synthetic leases are bounded.
            if outer is not None: outer.stop()
            if parent is not None and parent.poll() is None: parent.kill(); parent.wait(timeout=2)
            time.sleep(2.1 if not (Path(scope[0]).parent / 'cancelled').exists() else .05)

    def test_nested_outer_timeout(self): self.nested('timeout')
    def test_nested_outer_normal_exit(self): self.nested('normal')
    def test_nested_outer_explicit_cancel(self): self.nested('explicit')
    def test_nested_scope_flag(self): self.nested('flag')
    def test_nested_parent_sigkill(self): self.nested('parentdeath')

    def test_inherit_pointer_without_explicit_scope(self):
        scope = self.scope()
        pointer = self.base / 'active-scope.json'
        write(pointer, {'path': scope[0], 'sha256': scope[1]})
        with mock.patch.dict(os.environ, {'INVESTOPS_SCOPE_POINTER': str(pointer)}):
            child = r.OwnedTrial(subprocess.Popen, [sys.executable, '-c', 'pass'], timeout=2, revoke_scope=True)
            self.assertEqual(child.wait(), 0)
        self.assertTrue((Path(scope[0]).parent / 'cancelled').exists())

    def supervised_plan(self):
        self.pointer = self.base / 'active-scope.json'
        self.plan['supervisor_scope'] = str(self.pointer)
        write(self.planpath, self.plan)
        scope = self.scope()
        write(self.pointer, {'path': scope[0], 'sha256': scope[1]})
        return scope

    def test_run_rejects_expired_cancelled_and_mismatched_context_without_charge(self):
        scope = self.supervised_plan(); self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan')
            expired = self.scope(name='expired', seconds=-1)
            for current in (expired, scope):
                if current == scope: r.revoke_scope(scope)
                write(self.pointer, {'path': current[0], 'sha256': current[1]})
                with self.assertRaises(r.Blocked): runner.run_trial()
                self.assertEqual(len(runner.starts()), 0)
            live = self.scope(name='live')
            write(self.pointer, {'path': live[0], 'sha256': live[1]})
            for env in ({'INVESTOPS_SCOPE_POINTER': str(self.base / 'other.json')},
                        {'INVESTOPS_SCOPE_FILE': scope[0], 'INVESTOPS_SCOPE_SHA256': scope[1]}):
                with mock.patch.dict(os.environ, env), self.assertRaises(r.Blocked): runner.run_trial()
                self.assertEqual(len(runner.starts()), 0)
            # Mutable-pointer validation is RUN-only, never historical evidence.
            self.assertEqual(runner.verify()['state'], 'ready_trial')

    def test_supervised_plan_no_scope_blocks_before_attempt(self):
        self.supervised_plan(); self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan')
            self.pointer.unlink()
            self.assertEqual(runner.verify()['state'], 'ready_trial')
            with self.assertRaises((r.Blocked, OSError)): runner.run_trial()
            self.assertEqual(len(runner.starts()), 0)

    def test_scope_pointer_advances_across_resume_not_provenance(self):
        first = self.supervised_plan(); self.init()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            self.checkpoint(runner, 'plan'); runner.step()
            config = runner.config
        self.assertFalse((Path(first[0]).parent / 'cancelled').exists())
        r.revoke_scope(first)
        scope = first
        for i in range(2):
            scope = self.scope(name='resume' + str(i))
            write(self.pointer, {'path': scope[0], 'sha256': scope[1]})
            with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
                self.assertEqual(runner.config, config)
                runner.step()
        with r.Runner(self.registry, self.plan['set_id'], launch=self.launch) as runner:
            runner.step(); self.checkpoint(runner, 'selection'); runner.step(); runner.step()
            self.assertEqual(runner.verify()['state'], 'completed')
        r.revoke_scope(scope)
        with r.Runner(self.registry, self.plan['set_id']) as runner:
            self.assertEqual(runner.verify()['state'], 'completed')
            with mock.patch.object(r.time, 'time', return_value=time.time() + 3600):
                self.assertEqual(runner.verify()['state'], 'completed')
        self.pointer.unlink()
        with r.Runner(self.registry, self.plan['set_id']) as runner:
            self.assertEqual(runner.verify()['state'], 'completed')

    def test_init_rejects_dropped_or_mismatched_supervisor_environment(self):
        scope = self.scope()
        pointer = self.base / 'active-scope.json'
        write(pointer, {'path': scope[0], 'sha256': scope[1]})
        with mock.patch.dict(os.environ, {'INVESTOPS_SCOPE_POINTER': str(pointer)}):
            with self.assertRaises(r.Blocked): self.init()
        with mock.patch.dict(os.environ, {'INVESTOPS_SCOPE_FILE': scope[0], 'INVESTOPS_SCOPE_SHA256': scope[1]}):
            with self.assertRaises(r.Blocked): self.init()
        self.plan['supervisor_scope'] = str(self.base / 'different.json'); write(self.planpath, self.plan)
        with mock.patch.dict(os.environ, {'INVESTOPS_SCOPE_POINTER': str(pointer)}):
            with self.assertRaises(r.Blocked): self.init()

    def test_two_inner_trials_share_scope_without_revoking_owner(self):
        scope = self.scope()
        code = ('import sys,subprocess; sys.path.insert(0,' + repr(str(ROOT / 'tools')) + '); '
                'import research_set as r; '
                '\nfor i in range(2):\n'
                ' c=r.OwnedTrial(subprocess.Popen,[sys.executable,"-c","pass"],timeout=1)\n'
                ' assert c.wait()==0\n'
                ' r.validate_scope(' + repr(scope) + ')\n')
        outer = r.OwnedTrial(subprocess.Popen, [sys.executable, '-c', code], timeout=3,
                             execution_scope=scope, revoke_scope=True)
        self.assertEqual(outer.wait(), 0)
        self.assertTrue((Path(scope[0]).parent / 'cancelled').exists())

    def test_scope_and_pointer_security_before_launch(self):
        scope = self.scope()
        path = Path(scope[0]); original = path.read_bytes()
        pointer = self.base / 'active-scope.json'
        write(pointer, {'path': scope[0], 'sha256': scope[1]})
        def rejected(value=scope):
            launch = mock.Mock()
            with self.assertRaises((r.Blocked, OSError, TypeError)):
                r.OwnedTrial(launch, ['synthetic'], timeout=1, execution_scope=value)
            launch.assert_not_called()
        for obj in ({'schema_version': 1, 'expires_at': time.time()-1, 'token': 'safe'},
                    {'schema_version': 1, 'expires_at': True, 'token': 'safe'},
                    {'schema_version': 1, 'expires_at': time.time()+5, 'token': '../unsafe'},
                    {'schema_version': 2, 'expires_at': time.time()+5, 'token': 'safe'}):
            write(path, obj); rejected((str(path), r.digest(path.read_bytes())))
        write(path, original)
        rejected((str(path), '0'*64))
        path.chmod(0o644); rejected(); path.chmod(0o600)
        path.parent.chmod(0o755); rejected(); path.parent.chmod(0o700)
        alias = self.base / 'scope-link'; alias.symlink_to(path); rejected((str(alias), scope[1])); alias.unlink()
        os.link(path, alias); rejected(); alias.unlink()
        r.revoke_scope(scope); rejected()
        self.assertEqual((path.parent / 'cancelled').stat().st_mode & 0o777, 0o600)
        before = (path.parent / 'cancelled').read_bytes()
        r.revoke_scope(scope)
        self.assertEqual((path.parent / 'cancelled').read_bytes(), before)
        for obj in ({'path': scope[0]}, {'path': scope[0], 'sha256': 'not-a-hash'},
                    {'path': scope[0], 'sha256': scope[1], 'command': 'forbidden'}):
            write(pointer, obj)
            with self.assertRaises(r.Blocked): r.pointer_scope(pointer)

    def test_owner_launch_error_revokes_scope(self):
        scope = self.scope()
        def fail(*args, **kwargs): raise OSError('synthetic')
        child = r.OwnedTrial(fail, ['synthetic'], timeout=1, execution_scope=scope, revoke_scope=True)
        with self.assertRaises(r.Blocked): child.wait()
        self.assertTrue((Path(scope[0]).parent / 'cancelled').exists())

    def test_scope_deadline_bounds_owned_trial_and_revokes(self):
        scope = self.scope(seconds=.2)
        before = time.monotonic()
        child = r.OwnedTrial(subprocess.Popen, [sys.executable, '-c', 'import time; time.sleep(3)'],
                             timeout=2, execution_scope=scope, revoke_scope=True)
        child.wait()
        self.assertTrue(child.timed_out)
        self.assertLess(time.monotonic() - before, 1)
        self.assertTrue((Path(scope[0]).parent / 'cancelled').exists())


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
