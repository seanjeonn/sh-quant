"""Offline vertical tests for #57; subprocesses never use network or credentials."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import signal
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/collect_universe.py'


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.base.chmod(0o700)
        self.output = self.base / 'snapshot'
        (self.base / 'env').write_bytes(b'')
        (self.base / 'env').chmod(0o600)
        self.catalog = self.base / 'catalog.json'
        self.catalog.write_text(json.dumps({
            'schema_version': 1, 'universe_id': 'synthetic',
            'classification_as_of': '2025-01-01', 'point_in_time': False,
            'selection_policy': 'offline test', 'limitations': ['synthetic only'],
            'instruments': [
                {'market': 'US', 'ticker': 'AAA', 'source_symbol': 'AAA', 'themes': ['test']},
                {'market': 'KR', 'ticker': '000001', 'source_symbol': '000001', 'themes': ['test']},
            ]}))
        self.catalog.chmod(0o600)

    def args(self, **changes):
        values = {'universe-file': self.catalog, 'env-file': self.base / 'env',
                  'token-file': self.base / 'token', 'output': self.output,
                  'start-date': '2020-01-01', 'cutoff-exclusive': '2025-01-01',
                  'max-attempts': 6000, 'max-minutes': 120, 'batch-size': 12}
        values.update(changes)
        return [str(x) for pair in values.items() for x in ('--' + pair[0], pair[1])]

    def cli(self, *extra, **changes):
        return subprocess.run([sys.executable, str(SCRIPT), *self.args(**changes), *extra],
                              capture_output=True, text=True, timeout=15)

    def fake_runner(self):
        fake = self.base / 'fake_child.py'
        fake.write_text('''import argparse, csv, datetime as dt, hashlib, io, json, os
from pathlib import Path
p=argparse.ArgumentParser()
for key in ('env-file','token-file','output','universe-file','start-date','cutoff-exclusive','max-attempts','max-minutes','min-interval'):
    p.add_argument('--'+key, required=True)
a=p.parse_args()
out=Path(a.output); out.mkdir(mode=0o700)
def put(name, raw):
    fd=os.open(out/name, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd,'wb') as f: f.write(raw)
raw=Path(a.universe_file).read_bytes(); u=json.loads(raw)
put('universe.json',raw)
put('invocation.json',json.dumps(vars(a)).encode())
mode=Path(a.env_file)
if mode.exists() and mode.read_text() == 'fail':
    print('SECRET_MUST_NOT_ESCAPE'); raise SystemExit(3)
if mode.exists() and mode.read_text() in ('sleep','tree'):
    import time, subprocess, sys
    (mode.parent/'fake.pid').write_text(str(os.getpid()))
    if mode.read_text() == 'tree':
        descendant=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
        (mode.parent/'descendant.pid').write_text(str(descendant.pid))
    time.sleep(60)
if mode.exists() and mode.read_text() == 'orphan':
    import subprocess, sys
    descendant=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
    (mode.parent/'descendant.pid').write_text(str(descendant.pid))
entries=[]
rows=[]
day=dt.date(2021,1,1)
while day<dt.date(2025,1,1):
    if day.weekday()<5: rows.append([str(day),1,2,1,2,3])
    day+=dt.timedelta(days=1)
if mode.exists() and mode.read_text() == 'bad-csv':
    rows[0][1]='nan'
buf=io.StringIO(); w=csv.writer(buf,lineterminator='\\n')
w.writerow(['date','open','high','low','close','volume']); w.writerows(rows)
csvraw=buf.getvalue().encode()
for i in u['instruments']:
    name=i['market']+'_'+i['ticker']+'.csv'; put(name,csvraw)
    entries.append(dict(market=i['market'],ticker=i['ticker'],source_symbol=i['source_symbol'],
      path=name,sha256=hashlib.sha256(csvraw).hexdigest(),rows=len(rows),first=rows[0][0],last=rows[-1][0],
      observed_history_start=rows[0][0],starts_after_requested_start=True,quality={},
      currency='USD' if i['market']=='US' else 'KRW',session='US_REGULAR' if i['market']=='US' else 'KR_INTEGRATED'))
m=dict(schema_version=3,provider='toss',adjusted=True,timezone='Asia/Seoul',status='complete',
 start_date=a.start_date,cutoff_exclusive=a.cutoff_exclusive,prepared_at='2025-01-01T00:00:00+00:00',
 universe=dict(path='universe.json',sha256=hashlib.sha256(raw).hexdigest()),entries=entries,
 http_attempts=1,quality={},provenance={})
if mode.exists() and mode.read_text() == 'bad-source':
    m['entries'][0]['source_symbol']='WRONG'
if mode.exists() and mode.read_text() == 'partial':
    m['entries'].pop()
if mode.exists() and mode.read_text() == 'bad-cutoff':
    m['cutoff_exclusive']='2025-01-02'
if mode.exists() and mode.read_text() == 'bad-schema':
    m['schema_version']=3.0
manifestraw=json.dumps(m).encode()
if mode.exists() and mode.read_text() == 'duplicate':
    manifestraw=manifestraw[:-1]+b',"provider":"toss"}'
put('manifest.json',manifestraw)
if mode.exists() and mode.read_text() == 'mutate':
    with open(__file__, 'a') as f: f.write('\\n# changed fake source\\n')
''')
        fake.chmod(0o600)
        wrapper = self.base / 'runner.py'
        wrapper.write_text('''import sys
sys.path.insert(0, %r)
import collect_universe
from pathlib import Path
import os
original=collect_universe.immutable
def checkpoint(path, raw):
    original(path, raw)
    stop=Path(%r)/'stop-after-first'
    if stop.exists() and path.name=='0000.result.json':
        stop.unlink()
        os._exit(77)
    stop=Path(%r)/'stop-after-intent'
    if stop.exists() and path.name=='0000.intent.json':
        stop.unlink()
        os._exit(77)
collect_universe.immutable=checkpoint
raise SystemExit(collect_universe.main(child_script=%r))
''' % (str(ROOT / 'tools'), str(self.base), str(self.base), str(fake)))
        wrapper.chmod(0o600)
        return wrapper

    def run_fake(self, *extra, **changes):
        runner = self.base / 'runner.py'
        if not runner.exists():
            runner = self.fake_runner()
        return subprocess.run([sys.executable, str(runner), *self.args(**changes), *extra],
                              capture_output=True, text=True, timeout=15)

    def test_complete_batches_preserve_full_order_exact_bytes_and_native_caps(self):
        result = self.run_fake(**{'batch-size': 1})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.output / 'universe.json').read_bytes(), self.catalog.read_bytes())
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertEqual(manifest['schema_version'], 3)
        self.assertEqual([e['ticker'] for e in manifest['entries']], ['AAA', '000001'])
        self.assertEqual(len(manifest['provenance']['batch_manifests']), 2)
        for n in range(2):
            batch = self.output / 'batches' / f'{n:04d}'
            call = json.loads((batch / 'invocation.json').read_bytes())
            self.assertEqual(int(call['max_attempts']), 600)
            self.assertLessEqual(float(call['max_minutes']), 20)
            self.assertGreaterEqual(float(call['min_interval']), .25)
            subset = json.loads((batch / 'universe.json').read_bytes())
            original = json.loads(self.catalog.read_bytes())
            self.assertEqual(subset['instruments'], [original['instruments'][n]])
            for key in original.keys() - {'instruments', 'universe_id'}:
                self.assertEqual(subset[key], original[key])
        for path in self.output.rglob('*'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)

    def test_resume_complete_is_read_only_and_nonresume_never_overwrites(self):
        self.assertEqual(self.run_fake().returncode, 0)
        before = {str(p.relative_to(self.output)): p.read_bytes()
                  for p in self.output.rglob('*') if p.is_file()}
        result = self.run_fake('--resume')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, {str(p.relative_to(self.output)): p.read_bytes()
                                 for p in self.output.rglob('*') if p.is_file()})
        self.assertEqual(self.run_fake().stdout.strip(), 'blocked: output_already_exists')

    def test_resume_refuses_changed_caps_catalog_source_plan_or_output_identity(self):
        self.assertEqual(self.run_fake().returncode, 0)
        for changes in ({'max-attempts': 5999}, {'max-minutes': 119}, {'batch-size': 1},
                        {'start-date': '2019-01-01'}, {'cutoff-exclusive': '2024-12-31'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.run_fake('--resume', **changes).returncode, 1)
        original = self.catalog.read_bytes()
        self.catalog.write_bytes(original + b'\n')
        self.assertEqual(self.run_fake('--resume').returncode, 1)
        self.catalog.write_bytes(original)
        fake = self.base / 'fake_child.py'
        saved = fake.read_bytes()
        fake.write_bytes(saved + b'\n# changed source\n')
        self.assertEqual(self.run_fake('--resume').returncode, 1)
        fake.write_bytes(saved)
        plan = self.output / 'plan.json'
        saved = plan.read_bytes()
        changed = json.loads(saved); changed['started_epoch'] += 3600
        plan.write_text(json.dumps(changed))
        self.assertEqual(self.run_fake('--resume').returncode, 1)
        plan.write_bytes(saved)
        renamed = self.base / 'renamed'
        self.output.rename(renamed)
        self.assertEqual(self.run_fake('--resume', output=renamed).returncode, 1)

    def test_resume_revalidates_each_child_manifest_catalog_and_csv(self):
        self.assertEqual(self.run_fake().returncode, 0)
        targets = [self.output / 'batches/0000/manifest.json',
                   self.output / 'batches/0000/universe.json',
                   self.output / 'batches/0000/US_AAA.csv',
                   self.output / 'catalogs/0000.json', self.output / 'manifest.json']
        for target in targets:
            with self.subTest(target=target.name):
                saved = target.read_bytes()
                target.write_bytes(saved + b'\n')
                self.assertEqual(self.run_fake('--resume').returncode, 1)
                target.write_bytes(saved)
        self.assertEqual(self.run_fake('--resume').returncode, 0)

    def test_private_paths_refuse_symlinks_hardlinks_git_and_insecure_modes(self):
        self.base.chmod(0o755)
        self.assertEqual(self.run_fake().returncode, 1)
        self.base.chmod(0o700)
        linked = self.base / 'linked'
        linked.symlink_to(self.base, target_is_directory=True)
        self.assertEqual(self.run_fake(output=linked / 'snapshot').returncode, 1)
        linked.unlink()
        (self.base / '.git').mkdir()
        self.assertEqual(self.run_fake().returncode, 1)
        (self.base / '.git').rmdir()
        alias = self.base / 'catalog-alias'
        os.link(self.catalog, alias)
        self.assertEqual(self.run_fake().returncode, 1)
        alias.unlink()
        (self.base / 'env').chmod(0o644)
        self.assertEqual(self.run_fake().returncode, 1)
        (self.base / 'env').chmod(0o600)
        self.assertEqual(self.run_fake().returncode, 0)
        csvpath = self.output / 'batches/0000/US_AAA.csv'
        os.link(csvpath, alias)
        self.assertEqual(self.run_fake('--resume').returncode, 1)
        alias.unlink()
        saved = csvpath.read_bytes(); csvpath.unlink(); csvpath.symlink_to(self.catalog)
        self.assertEqual(self.run_fake('--resume').returncode, 1)
        csvpath.unlink(); csvpath.write_bytes(saved); csvpath.chmod(0o600)
        self.assertEqual(self.run_fake('--resume').returncode, 0)

    def test_mutex_remains_locked_in_live_child_after_parent_death(self):
        runner = self.fake_runner()
        (self.base / 'env').write_text('sleep')
        parent = subprocess.Popen([sys.executable, str(runner), *self.args()],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        child_pid = None
        try:
            started = self.output / 'attempts/0000.started.json'
            deadline = time.monotonic() + 5
            while not started.exists() and time.monotonic() < deadline:
                if parent.poll() is not None:
                    break
                time.sleep(.02)
            self.assertTrue(started.exists(), 'durable child ownership evidence missing')
            child_pid = json.loads(started.read_bytes())['pid']
            lock = self.output / '.collection.lock'
            inode = lock.stat().st_ino
            self.assertEqual(self.run_fake('--resume').stdout.strip(), 'blocked: busy')
            parent.kill(); parent.communicate(timeout=3)
            self.assertEqual(self.run_fake('--resume').stdout.strip(), 'blocked: busy')
            self.assertEqual(lock.stat().st_ino, inode)
        finally:
            if child_pid is None and (self.base / 'fake.pid').exists():
                os.kill(int((self.base / 'fake.pid').read_text()), signal.SIGKILL)
            if child_pid is not None:
                try:
                    os.killpg(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if parent.poll() is None:
                parent.kill()
            parent.communicate(timeout=3)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = self.run_fake('--resume')
            if result.stdout.strip() != 'blocked: busy':
                break
            time.sleep(.02)
        self.assertEqual(result.stdout.strip(), 'blocked: incomplete_child')
        self.assertFalse((self.output / 'manifest.json').exists())

    def test_failed_child_has_immutable_evidence_and_is_never_retried(self):
        (self.base / 'env').write_text('fail')
        result = self.run_fake(**{'batch-size': 1})
        self.assertEqual(result.stdout.strip(), 'blocked: child_failed')
        self.assertEqual(result.stderr, '')
        self.assertNotIn('SECRET', result.stdout)
        attempts = self.output / 'attempts'
        self.assertTrue((attempts / '0000.result.json').exists(), 'failure receipt missing')
        receipt = json.loads((attempts / '0000.result.json').read_bytes())
        self.assertEqual(receipt['status'], 'blocked')
        self.assertEqual(receipt['code'], 'child_failed')
        self.assertEqual(json.loads((attempts / '0000.intent.json').read_bytes())['reserved_attempts'], 600)
        before = {str(p): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        (self.base / 'env').write_bytes(b'')
        self.assertEqual(self.run_fake('--resume', **{'batch-size': 1}).stdout.strip(), 'blocked: failed_child')
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.output.rglob('*') if p.is_file()})
        self.assertFalse((self.output / 'manifest.json').exists())
        self.assertFalse((self.output / 'batches/0001').exists())

    def test_total_wall_timeout_kills_owned_process_group_and_retains_failure(self):
        (self.base / 'env').write_text('tree')
        began = time.monotonic()
        result = self.run_fake(**{'max-minutes': .02})
        try:
            self.assertEqual(result.stdout.strip(), 'blocked: child_timeout')
            self.assertLess(time.monotonic() - began, 4)
            for pidfile in ('fake.pid', 'descendant.pid'):
                pid = int((self.base / pidfile).read_text())
                status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
                self.assertTrue(not status.stdout.strip() or status.stdout.lstrip().startswith('Z'), status.stdout)
            receipt = json.loads((self.output / 'attempts/0000.result.json').read_bytes())
            self.assertEqual(receipt['code'], 'child_timeout')
            self.assertFalse((self.output / 'manifest.json').exists())
            self.assertEqual(self.run_fake('--resume', **{'max-minutes': .02}).stdout.strip(), 'blocked: failed_child')
        finally:
            started = self.output / 'attempts/0000.started.json'
            if started.exists():
                try:
                    os.killpg(json.loads(started.read_bytes())['pid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_argument_errors_are_allowlisted_without_echoing_values(self):
        result = self.cli(**{'max-attempts': 'SECRET_MUST_NOT_ESCAPE'})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), 'blocked: invalid_arguments')
        self.assertEqual(result.stderr, '')
        result = self.cli('--unknown=SECRET_MUST_NOT_ESCAPE')
        self.assertEqual(result.stdout.strip(), 'blocked: invalid_arguments')
        self.assertEqual(result.stderr, '')

    def test_resume_pending_batch_pins_reservation_and_charges_remaining_cap(self):
        (self.base / 'stop-after-first').touch()
        options = {'batch-size': 1, 'max-attempts': 601}
        self.assertEqual(self.run_fake(**options).returncode, 77)
        self.assertFalse((self.output / 'manifest.json').exists())
        first = self.output / 'batches/0000/manifest.json'
        before = first.read_bytes()
        intent = self.output / 'attempts/0000.intent.json'
        saved = intent.read_bytes()
        changed = json.loads(saved); changed['reserved_attempts'] = 1
        intent.write_text(json.dumps(changed))
        self.assertEqual(self.run_fake('--resume', **options).returncode, 1)
        self.assertFalse((self.output / 'batches/0001').exists())
        intent.write_bytes(saved)
        result = self.run_fake('--resume', **options)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(first.read_bytes(), before)
        second = json.loads((self.output / 'batches/0001/invocation.json').read_bytes())
        self.assertEqual(int(second['max_attempts']), 1)
        root = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertEqual(root['provenance']['reserved_attempts'], 601)

    def test_source_change_during_run_prevents_next_launch(self):
        (self.base / 'env').write_text('mutate')
        result = self.run_fake(**{'batch-size': 1})
        self.assertEqual(result.stdout.strip(), 'blocked: source_changed')
        self.assertFalse((self.output / 'batches/0001').exists())
        self.assertFalse((self.output / 'manifest.json').exists())

    def test_exited_child_cannot_leave_running_descendants(self):
        (self.base / 'env').write_text('orphan')
        result = self.run_fake()
        pid = int((self.base / 'descendant.pid').read_text())
        try:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
            self.assertTrue(not status.stdout.strip() or status.stdout.lstrip().startswith('Z'), status.stdout)
        finally:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_total_attempt_exhaustion_never_publishes_partial_coverage(self):
        result = self.run_fake(**{'batch-size': 1, 'max-attempts': 600})
        self.assertEqual(result.stdout.strip(), 'blocked: total_budget_exhausted')
        self.assertFalse((self.output / 'manifest.json').exists())
        self.assertTrue((self.output / 'batches/0000/manifest.json').exists())
        self.assertFalse((self.output / 'batches/0001').exists())
        self.assertEqual(self.run_fake('--resume', **{'batch-size': 1, 'max-attempts': 600}).stdout.strip(),
                         'blocked: total_budget_exhausted')

    def test_resume_uses_original_wall_epoch_instead_of_resetting_budget(self):
        (self.base / 'stop-after-first').touch()
        options = {'batch-size': 1, 'max-minutes': .02}
        self.assertEqual(self.run_fake(**options).returncode, 77)
        original = (self.output / 'plan.json').read_bytes()
        time.sleep(1.3)
        result = self.run_fake('--resume', **options)
        self.assertEqual(result.stdout.strip(), 'blocked: total_budget_exhausted')
        self.assertEqual((self.output / 'plan.json').read_bytes(), original)
        self.assertFalse((self.output / 'batches/0001').exists())
        self.assertFalse((self.output / 'manifest.json').exists())

    def test_renamed_or_future_attempt_state_is_ambiguous_not_a_fresh_budget(self):
        (self.base / 'stop-after-intent').touch()
        options = {'batch-size': 1}
        self.assertEqual(self.run_fake(**options).returncode, 77)
        intent = self.output / 'attempts/0000.intent.json'
        renamed = intent.with_name('renamed.intent.json')
        intent.rename(renamed)
        result = self.run_fake('--resume', **options)
        self.assertEqual(result.stdout.strip(), 'blocked: ambiguous_state')
        self.assertFalse((self.output / 'batches/0000').exists())
        renamed.rename(intent.with_name('0001.intent.json'))
        self.assertEqual(self.run_fake('--resume', **options).stdout.strip(), 'blocked: ambiguous_state')
        self.assertFalse((self.output / 'batches/0000').exists())

    def test_success_exit_is_not_enough_for_invalid_or_partial_child_data(self):
        cases = {'bad-source': 'child_entry_mismatch', 'partial': 'incomplete_child',
                 'bad-cutoff': 'invalid_child_manifest', 'bad-csv': 'invalid_csv_ohlcv'}
        for mode, code in cases.items():
            with self.subTest(mode=mode):
                (self.base / 'env').write_text(mode)
                output = self.base / mode
                result = self.run_fake(output=output)
                self.assertEqual(result.stdout.strip(), 'blocked: ' + code)
                self.assertEqual(result.stderr, '')
                self.assertFalse((output / 'manifest.json').exists())
                self.assertEqual(self.run_fake('--resume', output=output).stdout.strip(), 'blocked: incomplete_child')

    def test_child_metadata_rejects_duplicate_keys_and_noninteger_schema(self):
        for mode, code in (('bad-schema', 'invalid_child_manifest'), ('duplicate', 'invalid_json')):
            with self.subTest(mode=mode):
                (self.base / 'env').write_text(mode)
                output = self.base / mode
                result = self.run_fake(output=output)
                self.assertEqual(result.stdout.strip(), 'blocked: ' + code)
                self.assertFalse((output / 'manifest.json').exists())

    def test_policy_caps_are_independent_of_native_daily_limit(self):
        for changes in ({'max-attempts': 6001}, {'max-minutes': 121}, {'batch-size': 0}):
            with self.subTest(changes=changes):
                result = self.cli(**changes)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout.strip(), 'blocked: invalid_budget')
                self.assertEqual(result.stderr, '')
                self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
