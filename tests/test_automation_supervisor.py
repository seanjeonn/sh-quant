"""Synthetic-only supervisor contracts (#33). No credentials or remote services."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import shutil
import datetime as dt
import signal
import sys
import time


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL).decode().strip()


class Fixture:
    def __init__(self, root):
        self.m = module(); self.root = Path(root).resolve(); self.root.chmod(0o700)
        self.profile = self.root / 'profiles' / 'investops'
        self.profile.mkdir(parents=True, mode=0o700)
        self.private = self.profile / 'private'; self.private.mkdir(mode=0o700)
        self.auto = self.private / 'automation'; self.auto.mkdir(mode=0o700)
        self.core = self.root / 'core'; self.core.mkdir()
        origin = SOURCE.parents[1]
        for folder in ('tools', 'src'):
            shutil.copytree(origin / folder, self.core / folder, ignore=shutil.ignore_patterns('__pycache__', 'automation_supervisor.py'))
        for name in ('Cargo.toml', 'Cargo.lock'):
            shutil.copy(origin / name, self.core / name)
        git(self.core, 'init', '-q'); git(self.core, 'add', '.')
        git(self.core, '-c', 'user.name=Fixture', '-c', 'user.email=f@invalid', 'commit', '-qm', 'synthetic')
        self.repo = self.core
        self.binary = self.root / 'fake-binary'; shutil.copyfile(Path(sys.executable).resolve(), self.binary); self.binary.chmod(0o700)
        self.cli = self.root / 'fake-hermes'; self.cli.write_text('#!/bin/sh\nexit 0\n'); self.cli.chmod(0o700)
        reg = self.auto / 'registry'; reg.mkdir(mode=0o700)
        canary = self.auto / 'synthetic'; canary.mkdir(mode=0o700)
        (self.profile / 'workspaces').mkdir(mode=0o700)
        self.config: dict = dict(schema_version=1, profile_home=str(self.profile), repo=str(self.repo), core_repo=str(self.core),
            engine_commit=git(self.core, 'rev-parse', 'HEAD'), binary=str(self.binary), binary_sha256=self.m.sha(self.binary.read_bytes()),
            hermes_executable=str(self.cli), private_root=str(self.auto), registry=str(reg),
            workspace_root=str(self.profile / 'workspaces' / 'sh-quant-auto'), env_file=str(self.profile / '.env'),
            token_file=str(self.private / 'toss-token.json'), supervisor_sha256=self.m.sha(SOURCE.read_bytes()),
            code_pins={str(p.relative_to(self.core)): self.m.sha(p.read_bytes()) for base in ('src', 'tools') for p in (self.core / base).rglob('*') if p.is_file()},
            daily_start='14:30', deadline='17:00', timezone='Asia/Seoul', daily_max_launches=4, daily_max_turns=80,
            daily_run_budget_seconds=1800, daily_wall_seconds=7200, weekly_max_turns=40, weekly_run_budget_seconds=900,
            canary_max_turns=8, canary_run_budget_seconds=120, acquisition_max_attempts=600, acquisition_max_minutes=20,
            min_interval=0.25, activation=False, canary=dict(registry=str(canary), set_id='2026-11-10_synthetic_native_canary', nonce='synthetic123'))
        for name in ('Cargo.toml', 'Cargo.lock'):
            self.config['code_pins'][name] = self.m.sha((self.core / name).read_bytes())
        self.configpath = self.private / 'config.json'
        self.save()

    def register(self, sid='2026-11-10_synthetic_pending', **overrides):
        from test_research_contract import plan
        from unittest.mock import patch
        s = self.supervisor()
        folder = self.auto / sid[:10]
        if not folder.exists(): self.m.mkdir(folder)
        if not (folder / 'snapshot').exists(): self.frozen(folder / 'snapshot')
        repo = s.worktree(sid[:10])
        manifest = folder / 'snapshot' / 'manifest.json'
        value = plan(); old = value['set_id']; value['set_id'] = sid
        for c in [value['baseline'], *value['variants']]: c['run_id'] = c['run_id'].replace(old, sid)
        value.update(engine_commit=self.config['engine_commit'], binary_sha256=self.config['binary_sha256'],
                     cargo_lock_sha256=self.m.sha((repo / 'Cargo.lock').read_bytes()),
                     data_manifest_sha256=self.m.sha(manifest.read_bytes()),
                     supervisor_scope=str(folder / 'active-scope.json'),
                     next_experiment={'hypothesis': 'Synthetic longer window comparison.', 'reason': 'Exposed OOS requires a fresh test.'})
        value.update(overrides)
        planpath = folder / 'plan.json'
        if not (folder / 'active-scope.json').exists():
            inv = self.m.mkdir(folder / 'fixture-scope')
            self.m.immutable(inv / 'scope.json', self.m.encode(dict(schema_version=1,expires_at=time.time()+120,token='synthetic')))
            self.m.atomic(folder / 'active-scope.json',dict(path=str(inv / 'scope.json'),sha256=self.m.sha((inv / 'scope.json').read_bytes())))
        self.m.immutable(planpath, self.m.encode(value))
        sys.modules['research_contract'] = s.core_module('research_contract')
        core = s.core_module('research_set')
        class Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None): return cls(2026, 11, 10, 15, tzinfo=dt.timezone(dt.timedelta(hours=9)))
        with patch.object(core.dt, 'datetime', Clock):
            core.initialize(Path(self.config['registry']), planpath, repo, self.binary, manifest)
        return folder

    def frozen(self, output, date='2026-11-10'):
        output.mkdir(mode=0o700)
        s = self.supervisor()
        universe = s.core_module('prepare_toss').UNIVERSE
        entries = []
        for market, tickers in universe.items():
            for ticker in tickers:
                raw = b'date,open,high,low,close,volume\n2026-01-01,1,1,1,1,1\n'
                name = market + '_' + ticker + '.toss.csv'
                self.m.immutable(output / name, raw)
                entries.append(dict(market=market, ticker=ticker, path=name, sha256=self.m.sha(raw)))
        self.m.immutable(output / 'manifest.json', self.m.encode(dict(schema_version=2, provider='toss', adjusted=True,
            timezone='Asia/Seoul', status='complete', cutoff_exclusive=date, entries=entries)))

    def activate(self, **kwargs):
        def probe(argv, **kw):
            kw['stdout'].write(b'CANARY_OK synthetic123\n'); return 0, False
        self.supervisor(executor=probe, verifier=lambda r, s: {'state': 'completed', 'set_id': s, 'attempt_count': 3}).run('canary')
        self.config['activation'] = True; self.save()
        return self.supervisor(**kwargs)

    def save(self):
        self.configpath.write_bytes(self.m.encode(self.config)); self.configpath.chmod(0o600)

    def supervisor(self, **kwargs):
        from unittest.mock import patch
        with patch.dict(os.environ, {'HERMES_HOME': str(self.profile)}):
            return self.m.Supervisor(self.configpath, now=lambda: dt.datetime(2026, 11, 10, 15, tzinfo=dt.timezone(dt.timedelta(hours=9))), **kwargs)
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'tools' / 'automation_supervisor.py'


def module():
    spec = importlib.util.spec_from_file_location('automation_supervisor', SOURCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ExpandedFixture(Fixture):
    """Private synthetic schema3 inputs; never runs a data worker."""
    def __init__(self, root):
        super().__init__(root)
        catalogs = self.core / 'universes'; catalogs.mkdir()
        self.catalog = catalogs / 'synthetic.json'
        self.catalog.write_bytes(self.m.encode(dict(schema_version=1, universe_id='synthetic',
            classification_as_of='2026-11-01', point_in_time=False,
            selection_policy='Synthetic fixture only', limitations=['Not historical membership'],
            instruments=[dict(market='US', ticker='TEST', source_symbol='TEST', themes=['synthetic']),
                         dict(market='KR', ticker='000001', source_symbol='000001', themes=['synthetic'])])))
        helper = self.core / 'tools' / 'refresh_toss.py'
        if not helper.exists(): helper.write_text('# synthetic worker placeholder; not executable\n')
        for p in (helper, self.catalog):
            self.config['code_pins'][str(p.relative_to(self.core))] = self.m.sha(p.read_bytes())
        git(self.core, 'add', '.')
        git(self.core, '-c', 'user.name=Fixture', '-c', 'user.email=f@invalid', 'commit', '-qm', 'synthetic expanded inputs')
        self.config['engine_commit'] = git(self.core, 'rev-parse', 'HEAD')
        self.seed = self.private / 'seed'
        self.expanded_frozen(self.seed, '2026-11-07')
        self.config['expanded_data'] = dict(universe_file=str(self.catalog),
            universe_sha256=self.m.sha(self.catalog.read_bytes()), seed_manifest=str(self.seed / 'manifest.json'),
            seed_manifest_sha256=self.m.sha((self.seed / 'manifest.json').read_bytes()),
            start_date='2000-01-01', refresh_policy='overlap200_prefix_carried_v1')
        self.save()

    def expanded_frozen(self, output, date):
        output.mkdir(mode=0o700)
        self.m.immutable(output / 'universe.json', self.catalog.read_bytes())
        days = []; day = dt.date(2021, 1, 1); cutoff = dt.date.fromisoformat(date)
        while day < cutoff:
            if day.weekday() < 5: days.append(day.isoformat())
            day += dt.timedelta(days=1)
        raw = ('date,open,high,low,close,volume\n' + ''.join(d + ',1,1,1,1,1\n' for d in days)).encode()
        entries = []
        for instrument in json.loads(self.catalog.read_bytes())['instruments']:
            us = instrument['market'] == 'US'; name = instrument['market'] + '.csv'
            self.m.immutable(output / name, raw)
            entries.append(dict(market=instrument['market'], ticker=instrument['ticker'],
                source_symbol=instrument['source_symbol'], currency='USD' if us else 'KRW',
                session='US_REGULAR' if us else 'KR_INTEGRATED', path=name, sha256=self.m.sha(raw),
                rows=len(days), first=days[0], last=days[-1], quality={}, observed_history_start=days[0],
                starts_after_requested_start=True))
        self.m.immutable(output / 'manifest.json', self.m.encode(dict(schema_version=3, provider='toss',
            status='complete', adjusted=True, timezone='Asia/Seoul', start_date='2000-01-01',
            prepared_at=date + 'T12:00:00+09:00', cutoff_exclusive=date, http_attempts=2, entries=entries,
            universe=dict(path='universe.json', sha256=self.m.sha(self.catalog.read_bytes())))))


class ExpandedPolicyTests(unittest.TestCase):
    def test_expanded_boundary_rejects_untrusted_catalog_seed_and_pins(self):
        cases = ('extra_key', 'missing_key', 'start', 'policy', 'catalog_path', 'catalog_hash',
                 'catalog_pin', 'seed_path', 'seed_hash', 'schema', 'cohort', 'source', 'rows',
                 'coverage', 'csv', 'catalog_bytes', 'point_in_time', 'single_market',
                 'refresh_pin', 'contract_pin', 'collector_pin')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                f = ExpandedFixture(tmp); cfg = f.config['expanded_data']
                if case == 'extra_key': cfg['extra'] = True
                elif case == 'missing_key': del cfg['refresh_policy']
                elif case == 'start': cfg['start_date'] = '2020-01-01'
                elif case == 'policy': cfg['refresh_policy'] = 'unsafe'
                elif case in ('catalog_path', 'seed_path'):
                    key = 'universe_file' if case == 'catalog_path' else 'seed_manifest'
                    target = f.root / Path(cfg[key]).name; shutil.copyfile(cfg[key], target); target.chmod(0o600)
                    cfg[key] = str(target)
                elif case in ('catalog_hash', 'seed_hash'):
                    cfg['universe_sha256' if case == 'catalog_hash' else 'seed_manifest_sha256'] = '0' * 64
                elif case == 'catalog_pin': f.config['code_pins']['universes/synthetic.json'] = '0' * 64
                elif case.endswith('_pin'):
                    name = dict(refresh_pin='refresh_toss', contract_pin='universe_contract', collector_pin='collect_universe')[case]
                    del f.config['code_pins']['tools/' + name + '.py']
                elif case in ('point_in_time', 'single_market'):
                    value = json.loads(f.catalog.read_bytes())
                    if case == 'point_in_time': value['point_in_time'] = True
                    else: value['instruments'].pop()
                    f.catalog.write_bytes(f.m.encode(value))
                    cfg['universe_sha256'] = f.m.sha(f.catalog.read_bytes())
                    f.config['code_pins']['universes/synthetic.json'] = cfg['universe_sha256']
                elif case == 'catalog_bytes': (f.seed / 'universe.json').write_bytes(b'{}')
                elif case == 'csv': (f.seed / 'US.csv').write_bytes(b'invalid')
                else:
                    p = f.seed / 'manifest.json'; value = json.loads(p.read_bytes())
                    if case == 'schema': value['schema_version'] = 2
                    elif case == 'cohort': value['entries'].pop()
                    elif case == 'source': value['entries'][0]['source_symbol'] = 'WRONG'
                    elif case == 'rows': value['entries'][0]['rows'] = 1
                    elif case == 'coverage': value['entries'][0]['last'] = '2021-01-01'
                    p.write_bytes(f.m.encode(value)); cfg['seed_manifest_sha256'] = f.m.sha(p.read_bytes())
                f.save()
                with self.assertRaises((ValueError, OSError)):
                    f.supervisor()

    def prior(self, f, s, date, **changes):
        folder = f.m.mkdir(f.auto / date)
        f.expanded_frozen(folder / 'snapshot', date)
        ledger = dict(schema_version=1, date=date, started_epoch=s.day().timestamp(),
            policy_sha256=s.policy_sha256, status='blocked', launches=1, acquisition_attempts=1,
            snapshot_sha256=f.m.sha((folder / 'snapshot' / 'manifest.json').read_bytes()))
        ledger.update(changes); s.save_ledger(folder, ledger)
        return folder

    def test_base_selection_seed_or_newest_same_policy_data_not_research_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = ExpandedFixture(tmp); s = f.supervisor()
            seed = (f.seed / 'manifest.json', f.config['expanded_data']['seed_manifest_sha256'])
            self.assertEqual(s.select_base('2026-11-10'), seed)
            self.prior(f, s, '2026-11-08')
            latest = self.prior(f, s, '2026-11-09')
            self.prior(f, s, '2026-11-10')  # current day is never a base
            self.prior(f, s, '2026-11-11')  # neither is a future day
            self.assertEqual(s.select_base('2026-11-10'),
                (latest / 'snapshot' / 'manifest.json', f.m.read_json(latest / 'ledger.json')['snapshot_sha256']))

    def test_base_selection_ignores_old_policy_without_relabeling(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = ExpandedFixture(tmp); s = f.supervisor()
            old = self.prior(f, s, '2026-11-09', policy_sha256='0' * 64)
            (old / 'snapshot' / 'manifest.json').write_bytes(b'legacy unrelated bytes')
            before = {p: p.read_bytes() for p in old.rglob('*') if p.is_file()}
            self.assertEqual(s.select_base('2026-11-10')[0], f.seed / 'manifest.json')
            self.assertEqual(before, {p: p.read_bytes() for p in old.rglob('*') if p.is_file()})

    def test_latest_matching_base_corruption_never_silently_falls_back(self):
        for case in ('hash', 'missing_hash', 'csv', 'catalog', 'cutoff', 'cohort', 'ledger'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                f = ExpandedFixture(tmp); s = f.supervisor()
                self.prior(f, s, '2026-11-08'); latest = self.prior(f, s, '2026-11-09')
                p = latest / 'snapshot' / 'manifest.json'
                if case == 'hash': p.write_bytes(p.read_bytes() + b' ')
                elif case == 'csv': (p.parent / 'US.csv').write_bytes(b'bad')
                elif case in ('catalog', 'cutoff', 'cohort'):
                    value = json.loads(p.read_bytes())
                    if case == 'catalog': value['universe']['sha256'] = '0' * 64
                    elif case == 'cutoff': value['cutoff_exclusive'] = '2026-11-10'
                    else: value['entries'].pop()
                    p.write_bytes(f.m.encode(value))
                    ledger = s.read_ledger(latest); ledger['snapshot_sha256'] = f.m.sha(p.read_bytes()); s.save_ledger(latest, ledger)
                elif case == 'missing_hash':
                    # A complete acquisition without its immutable binding is not trusted.
                    for ledgerpath in latest.glob('ledger*.json'):
                        value = json.loads(ledgerpath.read_bytes()); del value['snapshot_sha256']
                        ledgerpath.write_bytes(f.m.encode(value))
                elif case == 'ledger':
                    value = json.loads((latest / 'ledger.json').read_bytes()); value['launches'] = 0
                    (latest / 'ledger.json').write_bytes(f.m.encode(value))
                with self.assertRaises(ValueError): s.select_base('2026-11-10')

    def test_seed_must_precede_target_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = ExpandedFixture(tmp); s = f.supervisor()
            with self.assertRaises(ValueError): s.select_base('2026-11-07')

    def test_expanded_daily_one_collector_and_frozen_model_input_with_seed_or_prior(self):
        for use_prior in (False, True):
            with self.subTest(use_prior=use_prior), tempfile.TemporaryDirectory() as tmp:
                f = ExpandedFixture(tmp); acquisitions = []; models = []
                folder = f.auto / '2026-11-10'; seedraw = {p: p.read_bytes() for p in f.seed.iterdir()}
                def execute(argv, **kw):
                    self.assertEqual(len(kw['pass_fds']), 1)
                    os.fstat(kw['pass_fds'][0])
                    if '--output' in argv:
                        acquisitions.append(argv)
                        self.assertEqual(Path(argv[1]).name, 'refresh_toss.py')
                        options = dict(zip(argv[2::2], argv[3::2]))
                        self.assertEqual(options, {'--universe-file': str(f.catalog),
                            '--universe-sha256': f.config['expanded_data']['universe_sha256'],
                            '--base-manifest': str(base), '--base-sha256': basehash,
                            '--env-file': f.config['env_file'], '--token-file': f.config['token_file'],
                            '--output': str(folder / 'snapshot'), '--start-date': '2000-01-01',
                            '--cutoff-exclusive': '2026-11-10', '--max-attempts': '600',
                            '--max-minutes': '20', '--min-interval': '0.25'})
                        self.assertLessEqual(kw['timeout'], 1200)
                        f.expanded_frozen(Path(options['--output']), '2026-11-10')
                        p = folder / 'snapshot' / 'manifest.json'; value = json.loads(p.read_bytes())
                        value['provenance'] = dict(refresh=dict(policy='overlap200_prefix_carried_v1', base_manifest_sha256=basehash))
                        p.write_bytes(f.m.encode(value))
                    else:
                        ledger = f.m.read_json(folder / 'ledger.json')
                        digest = f.m.sha((folder / 'snapshot' / 'manifest.json').read_bytes())
                        self.assertEqual(ledger['snapshot_sha256'], digest)
                        self.assertEqual(ledger['base_manifest_sha256'], basehash)
                        prompt = Path(argv[argv.index('--query-file') + 1]).read_text()
                        evidence = json.loads(prompt.split('Frozen private evidence (never publish paths or market values):\n')[1])
                        self.assertEqual(evidence['manifest_sha256'], digest)
                        self.assertEqual(evidence['manifest'], str(folder / 'snapshot' / 'manifest.json'))
                        self.assertIn('NEVER acquire data', prompt)
                        models.append(argv)
                    return 0, False
                s = f.activate(executor=execute)
                if use_prior:
                    prior = self.prior(f, s, '2026-11-09'); base = prior / 'snapshot' / 'manifest.json'
                else: base = f.seed / 'manifest.json'
                basehash = f.m.sha(base.read_bytes())
                s.day_sets = lambda date: [dict(state='await_plan_checkpoint', set_id=date + '_synthetic')] if models else []
                self.assertEqual(s.run('daily'), '연구 대기 2026-11-10')
                self.assertEqual(s.run('continue'), '연구 대기 2026-11-10')
                ledger = s.read_ledger(folder)
                self.assertEqual((ledger['acquisition_attempts'], ledger['launches']), (1, 2))
                self.assertEqual(len(acquisitions), 1); self.assertEqual(len(models), 2)
                self.assertEqual(seedraw, {p: p.read_bytes() for p in f.seed.iterdir()})

    def test_acquisition_output_requires_bound_lineage_before_any_model(self):
        for case in ('missing', 'policy', 'base', 'partial', 'too_many_attempts'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                f = ExpandedFixture(tmp); calls = []
                def execute(argv, **kw):
                    calls.append(argv); self.assertIn('--output', argv, 'model must not launch')
                    out = Path(argv[argv.index('--output') + 1]); f.expanded_frozen(out, '2026-11-10')
                    p = out / 'manifest.json'; value = json.loads(p.read_bytes())
                    if case != 'missing':
                        value['provenance'] = dict(refresh=dict(policy='overlap200_prefix_carried_v1',
                            base_manifest_sha256=argv[argv.index('--base-sha256') + 1]))
                    if case == 'policy': value['provenance']['refresh']['policy'] = 'wrong'
                    if case == 'base': value['provenance']['refresh']['base_manifest_sha256'] = '0' * 64
                    if case == 'partial': value['status'] = 'partial'
                    if case == 'too_many_attempts': value['http_attempts'] = 601
                    p.write_bytes(f.m.encode(value)); return 0, False
                s = f.activate(executor=execute)
                self.assertEqual(s.run('daily'), '연구 차단 2026-11-10')
                ledger = s.read_ledger(f.auto / '2026-11-10')
                self.assertEqual((ledger['acquisition_attempts'], ledger['launches']), (1, 0))
                self.assertNotIn('snapshot_sha256', ledger)
                self.assertEqual(s.run('continue'), '')
                self.assertEqual(len(calls), 1)

    def test_base_selection_failure_blocks_day_without_collection_or_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = ExpandedFixture(tmp); s = f.activate(executor=lambda *a, **k: self.fail('no workers'))
            prior = self.prior(f, s, '2026-11-09')
            (prior / 'snapshot' / 'US.csv').write_bytes(b'bad')
            self.assertEqual(s.run('daily'), '연구 차단 2026-11-10')
            ledger = s.read_ledger(f.auto / '2026-11-10')
            self.assertEqual((ledger['acquisition_attempts'], ledger['launches']), (0, 0))
            self.assertEqual(s.run('daily'), '')

    def test_expanded_research_rejects_missing_or_changed_snapshot_binding(self):
        for binding in (None, '0' * 64):
            with self.subTest(binding=binding), tempfile.TemporaryDirectory() as tmp:
                f = ExpandedFixture(tmp); s = f.supervisor(executor=lambda *a, **k: self.fail('no model'))
                folder = f.m.mkdir(f.auto / '2026-11-10'); f.expanded_frozen(folder / 'snapshot', folder.name)
                ledger = dict(date=folder.name, launches=0, acquisition_attempts=1, started_epoch=s.day().timestamp())
                if binding is not None: ledger['snapshot_sha256'] = binding
                with self.assertRaises(ValueError): s.research(folder, ledger, folder / 'snapshot', 'daily')

    def test_expanded_snapshot_binding_cannot_be_rewritten_in_a_later_ledger_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = ExpandedFixture(tmp); s = f.supervisor(); folder = self.prior(f, s, '2026-11-09')
            ledger = s.read_ledger(folder); ledger['snapshot_sha256'] = '0' * 64
            s.save_ledger(folder, ledger)
            with self.assertRaises(ValueError): s.read_ledger(folder)

    def test_expanded_construction_never_reads_credential_file_values(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            f = ExpandedFixture(tmp)
            credentials = {Path(f.config[key]) for key in ('env_file', 'token_file')}
            for p in credentials: p.write_bytes(b'SYNTHETIC NOT A CREDENTIAL'); p.chmod(0o600)
            read_bytes = Path.read_bytes; read_text = Path.read_text
            def guarded_bytes(p, *a, **kw):
                self.assertNotIn(p, credentials, 'credential value read'); return read_bytes(p, *a, **kw)
            def guarded_text(p, *a, **kw):
                self.assertNotIn(p, credentials, 'credential value read'); return read_text(p, *a, **kw)
            with patch.object(Path, 'read_bytes', guarded_bytes), patch.object(Path, 'read_text', guarded_text):
                self.assertIsNotNone(f.supervisor())

    def test_optional_expanded_config_accepts_public_catalog_private_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = ExpandedFixture(tmp)
            self.assertIsNotNone(f.supervisor())


class PolicyTests(unittest.TestCase):
    def test_idle_continue_does_not_open_or_acquire_worker_lock(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); s = f.supervisor()
            with patch.object(f.m.fcntl, 'flock', side_effect=AssertionError('idle stole lock')):
                self.assertEqual(s.run('continue'), '')
            self.assertFalse((f.auto / '.supervisor.lock').exists())
            self.assertFalse((f.auto / '2026-11-10').exists())

    def test_concurrent_diagnostic_directory_creation_does_not_block_idle_tick(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); s = f.supervisor(); original = Path.mkdir
            def concurrent(p, *args, **kwargs):
                if p == f.auto / 'diagnostics':
                    original(p, *args, **kwargs)
                    raise FileExistsError('another invocation created private directory')
                return original(p, *args, **kwargs)
            with patch.object(Path, 'mkdir', concurrent):
                self.assertEqual(s.run('continue'), '')
            self.assertFalse((f.auto / '.supervisor.lock').exists())

    def test_kernel_overlap_continue_first_and_daily_first_without_workers(self):
        from unittest.mock import patch
        for first in ('continue', 'daily'):
            with self.subTest(first=first), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp); s = f.supervisor(); folder = f.auto / '2026-11-10'
                ready_r, ready_w = os.pipe(); release_r, release_w = os.pipe()
                original_diagnostic = s.diagnostic
                def diagnostic(mode, outcome, reason):
                    original_diagnostic(mode, outcome, reason)
                    if mode == 'continue' and reason == 'idle_continue':
                        os.write(ready_w, b'1'); os.read(release_r, 1)
                def daily(mode):
                    folder.mkdir(mode=0o700)
                    s.save_ledger(folder, dict(schema_version=1, date=folder.name, status='pending',
                        launches=2, acquisition_attempts=1, started_epoch=s.day().timestamp(), policy_sha256=s.policy_sha256))
                    if first == 'daily':
                        os.write(ready_w, b'1'); os.read(release_r, 1)
                    return ''
                pid = os.fork()
                if pid == 0:
                    try:
                        with patch.object(s, 'diagnostic', side_effect=diagnostic), \
                                patch.object(s, 'activated', return_value=None), patch.object(s, 'daily', side_effect=daily):
                            s.run(first)
                        os._exit(0)
                    except BaseException: os._exit(1)
                try:
                    import select
                    self.assertTrue(select.select([ready_r], [], [], 5)[0], 'child did not reach barrier')
                    self.assertEqual(os.read(ready_r, 1), b'1')
                    if first == 'continue':
                        with patch.object(s, 'activated', return_value=None), patch.object(s, 'daily', side_effect=daily):
                            self.assertEqual(s.run('daily'), '')
                    else:
                        before = (folder / 'ledger.json').read_bytes()
                        self.assertEqual(s.run('continue'), '')
                        self.assertEqual((folder / 'ledger.json').read_bytes(), before)
                    ledger = f.m.read_json(folder / 'ledger.json')
                    self.assertEqual((ledger['status'], ledger['launches'], ledger['acquisition_attempts']), ('pending', 2, 1))
                    os.write(release_w, b'1')
                    self.assertEqual(os.waitpid(pid, 0)[1], 0); pid = None
                finally:
                    if pid is not None:
                        os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
                    for fd in (ready_r, ready_w, release_r, release_w): os.close(fd)

    def test_continue_rechecks_missing_ledger_under_lock(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); s = f.supervisor(); folder = f.m.mkdir(f.auto / '2026-11-10')
            f.m.immutable(folder / 'ledger.json', b'{}\n')
            with patch.object(s, 'check_pins', side_effect=lambda: (folder / 'ledger.json').unlink()), \
                    patch.object(s, 'activated', side_effect=AssertionError('must recheck')):
                self.assertEqual(s.run('continue'), '')
            self.assertEqual(list(folder.iterdir()), [])

    def test_partial_day_directory_is_preserved_and_never_initialized(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); s = f.activate(executor=lambda *a, **k: self.fail('no workers'))
            folder = f.m.mkdir(f.auto / '2026-11-10')
            snapshot = f.m.mkdir(folder / 'snapshot'); f.m.immutable(snapshot / 'partial.json', b'PRIVATE')
            before = {p.relative_to(folder): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
            self.assertEqual(s.run('continue'), '')
            with self.assertRaises(ValueError): s.run('daily')
            after = {p.relative_to(folder): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
            self.assertEqual(after, before)

    def test_idle_guard_rejects_untrusted_missing_ledger_paths(self):
        for kind in ('day_link', 'broken_ledger_link', 'public_day'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp); s = f.supervisor(); folder = f.auto / '2026-11-10'
                if kind == 'day_link': folder.symlink_to(f.root / 'missing')
                else:
                    folder.mkdir(mode=0o700)
                    if kind == 'broken_ledger_link': (folder / 'ledger.json').symlink_to(f.root / 'missing')
                    else: folder.chmod(0o755)
                with self.assertRaises(ValueError): s.run('continue')
                self.assertFalse((f.auto / '.supervisor.lock').exists())

    def test_diagnostic_write_failure_stops_before_worker_or_day_creation(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); s = f.activate()
            calls = []
            with patch.object(f.m, 'immutable', side_effect=OSError('SECRET disk failure')), \
                    patch.object(s, 'daily', side_effect=lambda mode: calls.append(mode) or ''):
                with self.assertRaises(OSError): s.run('daily')
            self.assertEqual(calls, [])
            self.assertFalse((f.auto / '2026-11-10').exists())

    def test_untrusted_failure_marker_never_allows_a_fresh_day(self):
        for kind in ('directory_link', 'broken_marker_link', 'public_directory'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp); s = f.activate(executor=lambda *a, **k: self.fail('no workers'))
                folder = f.auto / 'failed-starts'
                if kind == 'directory_link': folder.symlink_to(f.root / 'missing')
                else:
                    folder.mkdir(mode=0o700)
                    if kind == 'broken_marker_link': (folder / '2026-11-10.json').symlink_to(f.root / 'missing')
                    else: folder.chmod(0o755)
                with self.assertRaises((ValueError, FileExistsError)): s.run('daily')
                self.assertFalse((f.auto / '2026-11-10').exists())

    def test_constructor_pin_failure_preserves_attempt_entry_epoch(self):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            zone = dt.timezone(dt.timedelta(hours=9))
            start = dt.datetime(2026, 11, 10, 14, 30, tzinfo=zone).timestamp()
            class Clock(dt.datetime):
                @classmethod
                def now(cls, tz=None): return cls(2026, 11, 10, 14, 31, tzinfo=zone)
            with patch.dict(os.environ, HERMES_HOME=str(f.profile)), \
                    patch.object(f.m.dt, 'datetime', Clock), patch.object(f.m.time, 'time', return_value=start), \
                    patch.object(f.m.Supervisor, 'check_pins', side_effect=f.m.Blocked('SECRET')), redirect_stdout(io.StringIO()):
                self.assertEqual(f.m.main(['--config', str(f.configpath), '--mode', 'daily']), 1)
            marker = f.m.read_json(f.auto / 'failed-starts' / '2026-11-10.json')
            self.assertEqual(marker['started_epoch'], start)

    def test_preledger_failure_latches_manual_only_across_policy_changes(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); s = f.activate(executor=lambda *a, **k: self.fail('no acquisition or model'))
            s.now = lambda: dt.datetime(2026, 11, 10, 14, 30, tzinfo=dt.timezone(dt.timedelta(hours=9)))
            with patch.object(s, 'activated', side_effect=f.m.Blocked('SECRET')):
                with self.assertRaises(ValueError): s.run('daily')
            marker = f.auto / 'failed-starts' / '2026-11-10.json'
            record = f.m.read_json(marker); raw = marker.read_bytes()
            self.assertEqual(record['started_epoch'], s.day().timestamp())
            self.assertEqual(record['policy_sha256'], s.policy_sha256)
            for hour, minute in ((14, 31), (15, 0), (23, 0)):
                s.now = lambda: dt.datetime(2026, 11, 10, hour, minute, tzinfo=dt.timezone(dt.timedelta(hours=9)))
                self.assertEqual(s.run('daily'), '연구 차단 2026-11-10')
                self.assertFalse((f.auto / '2026-11-10').exists())
            f.config['daily_max_turns'] = 79; f.save()
            changed = f.supervisor(executor=lambda *a, **k: self.fail('no policy reset'))
            self.assertEqual(changed.run('daily'), '연구 차단 2026-11-10')
            self.assertEqual(marker.read_bytes(), raw)
            # Repointing a valid private_root is also a policy change, not a
            # fresh daily budget. The failure guard stays at the profile anchor.
            alternate = f.private / 'alternate-automation'; alternate.mkdir(mode=0o700)
            registry = alternate / 'registry'; registry.mkdir(mode=0o700)
            f.config.update(private_root=str(alternate), registry=str(registry)); f.save()
            moved = f.supervisor(executor=lambda *a, **k: self.fail('no root reset'))
            self.assertEqual(moved.run('daily'), '연구 차단 2026-11-10')
            self.assertFalse((alternate / '2026-11-10').exists())
            self.assertEqual(marker.read_bytes(), raw)

    def test_missing_day_deadline_alerts_at_17_without_fabricating_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); s = f.supervisor(executor=lambda *a, **k: self.fail('no worker'))
            for hour, minute, expected in ((14, 0, ''), (16, 59, ''),
                                            (17, 0, '연구 차단 2026-11-10'),
                                            (23, 0, '연구 차단 2026-11-10')):
                s.now = lambda: dt.datetime(2026, 11, 10, hour, minute, tzinfo=dt.timezone(dt.timedelta(hours=9)))
                self.assertEqual(s.run('deadline'), expected)
                self.assertFalse((f.auto / '2026-11-10').exists())
            events = [f.m.read_json(p) for p in (f.auto / 'diagnostics').glob('*.json')]
            self.assertEqual(sum(e['reason'] == 'missing_day_deadline' and e['outcome'] == 'blocked' for e in events), 2)
            self.assertFalse((f.auto / '.supervisor.lock').exists())

    def test_daily_short_wait_acquires_only_after_real_owner_releases(self):
        import fcntl
        import select
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); s = f.supervisor()
            ready_r, ready_w = os.pipe(); release_r, release_w = os.pipe()
            pid = os.fork()
            if pid == 0:
                try:
                    fd = os.open(f.auto / '.supervisor.lock', os.O_CREAT | os.O_RDWR, 0o600)
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    os.write(ready_w, b'1'); os.read(release_r, 1); os.close(fd)
                    os._exit(0)
                except BaseException: os._exit(1)
            try:
                self.assertTrue(select.select([ready_r], [], [], 5)[0]); os.read(ready_r, 1)
                original = fcntl.flock; collisions = []
                def acquire(fd, flags):
                    try: return original(fd, flags)
                    except BlockingIOError:
                        if not collisions: os.write(release_w, b'1')
                        collisions.append(1); raise
                with patch.object(f.m.fcntl, 'flock', side_effect=acquire), \
                        patch.object(s, 'activated', return_value=None), patch.object(s, 'daily', return_value=''):
                    self.assertEqual(s.run('daily'), '')
                self.assertTrue(collisions)
                self.assertEqual(os.waitpid(pid, 0)[1], 0); pid = None
            finally:
                if pid is not None:
                    os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
                for fd in (ready_r, ready_w, release_r, release_w): os.close(fd)

    def test_real_kernel_busy_continue_is_quiet_and_daily_wait_is_bounded(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); s = f.supervisor()
            folder = f.m.mkdir(f.auto / '2026-11-10')
            f.m.immutable(folder / 'ledger.json', b'{}\n')
            original = (folder / 'ledger.json').read_bytes()
            fd = os.open(f.auto / '.supervisor.lock', os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(s.run('continue'), '')
                events = [f.m.read_json(p) for p in (f.auto / 'diagnostics').glob('*.json')]
                event, = [e for e in events if e['reason'] == 'lock_busy']
                self.assertEqual((event['reason'], event['outcome']), ('lock_busy', 'quiet'))
                start = time.monotonic()
                with self.assertRaises(ValueError): s.run('daily')
                self.assertLessEqual(time.monotonic() - start, 2.1)
                self.assertEqual((folder / 'ledger.json').read_bytes(), original)
                other = os.open(f.auto / '.supervisor.lock', os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError): fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally: os.close(other)
            finally: os.close(fd)

    def test_untrusted_argv_and_profile_redirect_cannot_escape_safe_diagnostics(self):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            other = f.root / 'profiles' / 'other'; other.mkdir(mode=0o700)
            foreign = other / 'private'; foreign.mkdir(mode=0o700)
            redirected = foreign / 'automation'; redirected.mkdir(mode=0o700)
            f.config.update(profile_home=str(other), private_root=str(redirected)); f.save()
            for argv in (['--config', str(f.configpath), '--mode', 'daily'],
                         ['--config', str(f.configpath), '--mode', 'SECRET/invalid']):
                out = io.StringIO()
                with patch.dict(os.environ, HERMES_HOME=str(f.profile)), redirect_stdout(out):
                    self.assertEqual(f.m.main(argv), 1)
                self.assertEqual(out.getvalue(), '자동화 차단\n')
            self.assertEqual(list(redirected.iterdir()), [])
            self.assertFalse((f.auto / 'failed-starts').exists())
            events = [f.m.read_json(p) for p in (f.auto / 'diagnostics').glob('*.json')]
            self.assertEqual({e['mode'] for e in events}, {'daily', 'unknown'})
            for p in (f.auto / 'diagnostics').glob('*.json'):
                self.assertNotIn('SECRET', p.read_text()); self.assertNotIn(str(f.root), p.read_text())
            before = set(f.root.rglob('*'))
            out = io.StringIO()
            with patch.dict(os.environ, HERMES_HOME=str(other)), redirect_stdout(out):
                self.assertEqual(f.m.main(['--config', str(f.configpath), '--mode', 'daily']), 1)
            self.assertEqual(set(f.root.rglob('*')), before)

    def test_safe_durable_cli_diagnostics_distinguish_constructor_and_receipt_failures(self):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        import io
        for reason in ('config_validation', 'pin_validation', 'canary_validation'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp)
                if reason == 'config_validation':
                    f.config['profile_home'] = str(f.root / 'SECRET-other-profile')
                    f.config['private_root'] = str(f.root / 'SECRET-redirect')
                elif reason == 'pin_validation': f.config['binary_sha256'] = 'a' * 64
                else: f.config['activation'] = True
                f.save(); out = io.StringIO()
                with patch.dict(os.environ, HERMES_HOME=str(f.profile)), redirect_stdout(out):
                    self.assertEqual(f.m.main(['--config', str(f.configpath), '--mode', 'daily']), 1)
                self.assertEqual(out.getvalue(), '자동화 차단\n')
                files = [p for p in (f.auto / 'diagnostics').glob('*.json') if f.m.read_json(p)['outcome'] == 'blocked']
                self.assertEqual(len(files), 1)
                event = f.m.read_json(files[0])
                self.assertEqual(event['reason'], reason)
                self.assertEqual(event['mode'], 'daily')
                self.assertEqual(event['outcome'], 'blocked')
                self.assertEqual(set(event), {'schema_version', 'mode', 'date', 'stage', 'outcome', 'reason', 'timestamp'})
                self.assertNotIn('SECRET', files[0].read_text())
                self.assertNotIn(str(f.root), files[0].read_text())
                self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
                self.assertEqual(files[0].parent.stat().st_mode & 0o777, 0o700)
                self.assertFalse((f.root / 'SECRET-redirect').exists())

    def test_repin_canary_generation_preserves_original_receipt_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.activate()
            originals = {p: p.read_bytes() for p in (f.auto / 'canary').rglob('*') if p.is_file()}
            old_receipt = (f.auto / 'canary-receipt.json').read_bytes()
            f.config['activation'] = False
            f.config['canary_generation'] = 'repin-synthetic-1'
            f.config['canary']['nonce'] = 'freshsynthetic123'
            f.save()
            def probe(argv, **kw):
                kw['stdout'].write(b'CANARY_OK freshsynthetic123\n')
                return 0, False
            s = f.supervisor(executor=probe, verifier=lambda r, sid: dict(state='completed', set_id=sid, attempt_count=3))
            self.assertEqual(s.run('canary'), '카나리 통과 freshsynthetic123')
            s.validate_canary_receipt()
            self.assertTrue((f.auto / 'canaries' / 'repin-synthetic-1' / 'receipt.json').exists())
            self.assertEqual((f.auto / 'canary-receipt.json').read_bytes(), old_receipt)
            for p, raw in originals.items(): self.assertEqual(p.read_bytes(), raw)
            self.assertEqual(s.run('canary'), '')

    def test_publication_pending_resumes_agent_without_reacquisition_and_respects_cap(self):
        for capped in (False, True):
            with self.subTest(capped=capped), tempfile.TemporaryDirectory() as tmp:
                f=Fixture(tmp); sid='2026-11-10_synthetic_resume'; calls=[]
                def execute(argv,**kw):
                    self.assertNotIn('--output',argv); calls.append(argv); return 0,False
                s=f.activate(executor=execute,verifier=lambda *a: dict(state='completed',set_id=sid,conclusion='defer',attempt_count=3))
                folder=f.register(sid)
                for name in ('report','evaluation'):
                    f.m.immutable(Path(f.config['registry'])/sid/(name+'.json'),b'{}\n')
                ledger=dict(schema_version=1,date='2026-11-10',status='publication_pending',launches=0,
                    acquisition_attempts=0,started_epoch=s.day().timestamp(),policy_sha256=s.policy_sha256)
                s.save_ledger(folder,ledger)
                if capped: s.now=lambda: dt.datetime(2026,11,10,17,tzinfo=dt.timezone(dt.timedelta(hours=9)))
                self.assertEqual(s.run('continue'),'연구 차단 2026-11-10' if capped else '연구 대기 2026-11-10')
                self.assertEqual(len(calls),0 if capped else 1)
                if not capped:
                    self.assertEqual(f.m.read_json(folder/'ledger.json')['status'],'publication_pending')
                    self.assertEqual(f.m.read_json(folder/'ledger.json')['launches'],1)

    def test_final_publication_requires_independent_remote_blob_pr_and_current_identity(self):
        from unittest.mock import patch
        for mutation in ('missing', 'remote', 'blob', 'pr_head', 'pr_base', 'pr_url', 'pr_files', 'valid',
                         'closed_in_main', 'closed_other_base', 'merged_in_main', 'closed_not_in_main', 'closed_diverged', 'draft_state'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                f=Fixture(tmp); sid='2026-11-10_synthetic_publication'
                s=f.activate(verifier=lambda *a: dict(state='completed',set_id=sid,conclusion='defer',attempt_count=3))
                folder=f.register(sid); wt=Path(f.config['workspace_root'])/'2026-11-10'
                for name in ('report','evaluation'):
                    f.m.immutable(Path(f.config['registry'])/sid/(name+'.json'),b'{"private":"secret"}\n')
                status=s.day_sets('2026-11-10')[0]
                raw=s.publication_descriptor(folder,status)
                git(f.core,'remote','add','origin','https://github.com/seanjeonn/sh-quant.git')
                git(f.core,'branch','-m','feature#33')
                # Worktree was made before origin existed; Git shares its config.
                rel='research/'+sid+'/publication.json'; target=wt/rel
                target.parent.mkdir(parents=True); target.write_bytes(raw if mutation!='blob' else b'wrong\n')
                git(wt,'add',rel); git(wt,'-c','user.name=Fixture','-c','user.email=f@invalid','commit','-qm','public descriptor')
                commit=git(wt,'rev-parse','HEAD')
                branch='research/2026-11-10_daily'; url='https://github.com/seanjeonn/sh-quant/pull/34'
                receipt=dict(schema_version=1,set_id=sid,pr_number=34,commit=commit,branch=branch,
                             report_path=rel,report_sha256=f.m.sha(raw),pr_url=url)
                if mutation!='missing': f.m.immutable(folder/'publication.json',f.m.encode(receipt))
                pr=dict(url=url,state='OPEN',baseRefName='feature#33',headRefName=branch,headRefOid=commit,
                        files=[dict(path=rel),dict(path='backlog.md'),dict(path='strategies/'+sid+'_baseline.toml')])
                if mutation=='pr_head': pr['headRefOid']='a'*40
                if mutation=='pr_base': pr['baseRefName']='main'
                if mutation=='pr_url': pr['url']='https://github.com/other/repo/pull/34'
                if mutation=='pr_files': pr['files'].append(dict(path='src/main.rs'))
                # #41: an archived PR is accepted only when its exact head is already contained in remote main.
                if mutation.startswith('closed'): pr['state']='CLOSED'
                if mutation=='merged_in_main': pr['state']='MERGED'
                # #45: after a re-pin the core checkout is no longer on the archived PR's original base.
                if mutation=='closed_other_base': pr['baseRefName']='feat/older-base'
                if mutation=='draft_state': pr['state']='UNKNOWN'
                compare=dict(closed_not_in_main='ahead',closed_diverged='diverged').get(mutation,'behind')
                s.github_reader=lambda kind,number: dict(status=compare) if kind=='compare' else pr
                original=s.git
                def read(repo,*args):
                    if args[0]=='ls-remote': return ('a'*40 if mutation=='remote' else commit)+'\trefs/heads/'+branch
                    return original(repo,*args)
                ledger=dict(schema_version=1,date='2026-11-10',status='running',launches=0,acquisition_attempts=0,
                            started_epoch=s.day().timestamp(),policy_sha256=s.policy_sha256)
                s.save_ledger(folder,ledger)
                with patch.object(s,'git',side_effect=read):
                    if mutation in ('missing','valid','closed_in_main','closed_other_base','merged_in_main'):
                        result=s.complete(folder,ledger,status)
                        self.assertEqual(ledger['status'],'publication_pending' if mutation=='missing' else 'completed')
                        self.assertIn('연구 대기' if mutation=='missing' else '연구 완료',result)
                        if mutation=='valid':
                            self.assertEqual(s.run('daily'),'')
                            (folder/'publication.json').unlink()
                            self.assertEqual(s.run('daily'),'연구 차단 2026-11-10')
                    else:
                        with self.assertRaises(ValueError): s.complete(folder,ledger,status)

    def test_publication_renderer_is_deterministic_public_safe_and_bypasses_worker_lock(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); sid='2026-11-10_synthetic_publish'
            s = f.activate(verifier=lambda *a: dict(state='completed',set_id=sid,conclusion='defer',attempt_count=3))
            folder = f.register(sid)
            for name in ('report', 'evaluation'):
                f.m.immutable(Path(f.config['registry']) / sid / (name+'.json'), b'{"private":"SECRET metrics"}\n')
            s.save_ledger(folder,dict(schema_version=1,date='2026-11-10',status='publication_pending',launches=0,
                acquisition_attempts=0,started_epoch=s.day().timestamp(),policy_sha256=s.policy_sha256))
            fd=os.open(f.auto / '.supervisor.lock',os.O_CREAT|os.O_RDWR,0o600)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                raw=s.run('publication')
                self.assertEqual(raw,s.run('publication'))
                self.assertEqual(raw,(folder / 'publication-descriptor.json').read_bytes())
                obj=json.loads(raw)
                self.assertEqual(obj['set_id'],sid); self.assertEqual(obj['conclusion'],'defer')
                self.assertEqual(obj['attempt_count'],3)
                self.assertNotIn('SECRET',raw.decode()); self.assertNotIn(str(f.root),raw.decode())
            finally: os.close(fd)

    def test_launch_scope_environment_and_nested_owned_trial_cannot_escape(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp); marker = f.auto / 'nested-pid'; envfile = f.auto / 'child-env'
                f.cli.write_text('#!' + sys.executable + '\n' + '''import os,sys,subprocess,time,json
from pathlib import Path
sys.path.insert(0, ''' + repr(str(f.core / 'tools')) + ''')
import research_set
Path(''' + repr(str(envfile)) + ''').write_text(json.dumps({k:v for k,v in os.environ.items() if k.startswith('INVESTOPS_') or k=='HERMES_HOME'}))
t = research_set.OwnedTrial(subprocess.Popen,[sys.executable,'-c','import time; time.sleep(30)'],timeout=30)
Path(''' + repr(str(marker)) + ''').write_text(str(t.pid))
''' + ('time.sleep(30)\n' if timeout else 'print("CANARY_OK synthetic123",flush=True)\n'))
                f.config['canary_run_budget_seconds'] = 1; f.save()
                s = f.supervisor(verifier=lambda r,sid: dict(state='completed',set_id=sid,attempt_count=3))
                if timeout:
                    with self.assertRaises(ValueError): s.run('canary')
                else: s.run('canary')
                inv = next((f.auto / 'canary').glob('invocation-*'))
                scope = f.m.read_json(inv / 'scope.json')
                self.assertEqual(scope['schema_version'], 1)
                self.assertTrue((inv / 'cancelled').exists())
                actual = json.loads(envfile.read_text())
                self.assertEqual(actual['HERMES_HOME'], str(f.profile))
                self.assertEqual(actual['INVESTOPS_SCOPE_FILE'], str(inv / 'scope.json'))
                self.assertEqual(actual['INVESTOPS_SCOPE_SHA256'], f.m.sha((inv / 'scope.json').read_bytes()))
                self.assertEqual(f.m.read_json(f.auto / 'canary' / 'active-scope.json'),
                    dict(path=actual['INVESTOPS_SCOPE_FILE'],sha256=actual['INVESTOPS_SCOPE_SHA256']))
                pid = int(marker.read_text())
                for _ in range(150):
                    result = subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True)
                    if result.returncode or result.stdout.strip().startswith('Z'): break
                    time.sleep(.02)
                else: self.fail('nested OwnedTrial escaped outer cleanup')

    def test_registered_inputs_are_independently_bound_despite_same_status(self):
        from unittest.mock import patch
        for field in ('engine_commit', 'manifest', 'manifest_sha256', 'binary', 'binary_sha256', 'repo', 'plan_source', 'supervisor_scope', 'valid'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp); sid = '2026-11-10_synthetic_bound'; folder = f.register(sid)
                s = f.supervisor(verifier=lambda *a: dict(state='completed', set_id=sid, conclusion='defer', attempt_count=3))
                core = s.core_module('research_set')
                # A registered runner is valid on its own. Feed its real config/plan
                # through a read-only runner proxy to test supervisor-relative binding.
                with core.Runner(f.config['registry'], sid) as runner:
                    config = dict(runner.config); plan = dict(runner.plan)
                if field in ('engine_commit', 'supervisor_scope'): plan[field] = 'a' * 40 if field == 'engine_commit' else str(folder / 'wrong.json')
                elif field != 'valid': config[field] = 'a' * 64 if field.endswith('sha256') else str(folder / 'wrong')
                class Registered:
                    def __enter__(self): self.config=config; self.plan=plan; return self
                    def __exit__(self, *args): pass
                    def verify(self): return dict(state='completed', set_id=sid, conclusion='defer', attempt_count=3)
                load = s.core_module
                with patch.object(core, 'Runner', lambda *a: Registered()), patch.object(s, 'core_module', side_effect=lambda name: core if name == 'research_set' else load(name)):
                    if field == 'valid': self.assertEqual(s.day_sets('2026-11-10')[0]['state'], 'completed')
                    else:
                        with self.assertRaises(ValueError): s.day_sets('2026-11-10')

    def test_weekly_independent_issue_identity_and_body_proof(self):
        from unittest.mock import patch
        for mutation in ('missing', 'body', 'identity', 'valid'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp)
                git(f.core, 'remote', 'add', 'origin', 'https://github.com/seanjeonn/sh-quant.git')
                url = 'https://github.com/seanjeonn/sh-quant/issues/33'
                def execute(argv, **kw):
                    f.m.immutable(f.auto / 'week-2026-W46' / 'weekly-review.json', f.m.encode(dict(
                        schema_version=1, completed=True, reviewed_at='2026-11-10T15:00:00+09:00',
                        managed_issue_urls=[url], managed_issue_body_sha256={url: f.m.sha(b'actual body')})))
                    return 0, False
                def reader(kind, number):
                    if mutation == 'missing': raise ValueError('not found')
                    return dict(number=number, url=url if mutation != 'identity' else url+'0',
                                state='OPEN', body='actual body' if mutation != 'body' else 'changed')
                s = f.activate(executor=execute)
                s.github_reader = reader
                self.assertEqual(s.run('weekly'), '주간 검토 완료 1' if mutation == 'valid' else '주간 검토 차단')

    def test_actual_profile_env_and_existing_readonly_synthetic_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.config['env_file'] = str(f.profile / '.env')
            existing = f.private / 'readonly-synthetic-registry'
            existing.mkdir(mode=0o700)
            f.config['canary']['registry'] = str(existing)
            f.save()
            self.assertIsNotNone(f.supervisor())
            outside = f.root / 'outside-synthetic'; outside.mkdir(mode=0o700)
            f.config['canary']['registry'] = str(outside); f.save()
            with self.assertRaises(ValueError): f.supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.config['env_file'] = str(f.profile / 'profile.env'); f.save()
            with self.assertRaises(ValueError): f.supervisor()

    def test_continue_uses_kst_date_even_when_clock_is_utc(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); s = f.activate(executor=lambda *a, **k: self.fail('no model'))
            s.now = lambda: dt.datetime(2026, 11, 9, 16, tzinfo=dt.timezone.utc)
            folder = f.m.mkdir(f.auto / '2026-11-10')
            s.save_ledger(folder, dict(schema_version=1, date='2026-11-10', status='running', launches=0,
                acquisition_attempts=0, started_epoch=s.day().timestamp(), policy_sha256=s.policy_sha256))
            self.assertEqual(s.run('continue'), '연구 차단 2026-11-10')

    def test_research_prompt_names_machine_policy_and_private_plan_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); s = f.supervisor()
            prompt = s.research_prompt(f.auto, f.auto / 'manifest.json', 'a' * 64, f.core, {'date': '2026-11-10'})
            for token in ('mean_is_sharpe_v1', 'sharpe_excess_mdd_v1', 'plan.json', 'exposed OOS',
                          'checkpoint', 'private_day', 'NEVER acquire data', 'feature tracking issue',
                          'plan.supervisor_scope', 'active-scope.json', str(f.configpath), '--mode publication',
                          'publication.json', 'report_sha256', 'pr_number'):
                self.assertIn(token, prompt)

    def test_actual_four_model_launches_stop_without_fifth_or_reacquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); models = []; acquisitions = []
            def execute(argv, **kw):
                if '--output' in argv:
                    acquisitions.append(argv); f.frozen(Path(argv[argv.index('--output') + 1]))
                else:
                    models.append(argv)
                    p = Path(f.config['registry']) / '2026-11-10_synthetic_pending'
                    if not p.exists(): f.register(p.name)
                return 0, False
            verify = lambda r, sid: dict(state='ready_trial', set_id=sid, attempt_count=0)
            s = f.activate(executor=execute, verifier=verify)
            self.assertEqual(s.run('daily'), '연구 대기 2026-11-10')
            for _ in range(2):
                s = f.supervisor(executor=execute, verifier=verify)
                self.assertEqual(s.run('continue'), '연구 대기 2026-11-10')
            self.assertEqual(s.run('continue'), '연구 차단 2026-11-10')
            self.assertEqual(s.run('continue'), '')
            self.assertEqual(len(models), 4); self.assertEqual(len(acquisitions), 1)
            self.assertEqual(f.m.read_json(f.auto / '2026-11-10' / 'ledger.json')['launches'], 4)

    def test_config_types_future_keys_permissions_and_core_drift_are_rejected(self):
        mutations = (('daily_max_turns', True), ('daily_max_turns', 81), ('activation', 1),
                     ('schema_version', 2), ('timezone', 'UTC'), ('min_interval', .1), ('future', 'unsafe'))
        for key, value in mutations:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp); f.config[key] = value; f.save()
                with self.assertRaises(ValueError): f.supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); f.configpath.chmod(0o644)
            with self.assertRaises(ValueError): f.supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); p = f.core / 'tools' / 'unexpected.py'; p.write_text('print("unsafe")')
            with self.assertRaises(ValueError): f.supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); p = f.core / 'Cargo.lock'; p.write_text('drift')
            with self.assertRaises(ValueError): f.supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            from unittest.mock import patch
            with patch.dict(os.environ, {'HERMES_HOME': str(f.root / 'other')}):
                with self.assertRaises(ValueError): f.m.Supervisor(f.configpath)

    def test_zero_exit_provider_403_is_not_accepted_or_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            def execute(argv, **kw):
                kw['stdout'].write(b'Error code: 403 private-provider\nCANARY_OK synthetic123\n')
                return 0, False
            s = f.supervisor(executor=execute, verifier=lambda r, sid: dict(state='completed', set_id=sid, attempt_count=3))
            with self.assertRaises(ValueError): s.run('canary')
            self.assertFalse((f.auto / 'canary-receipt.json').exists())
            with self.assertRaises(ValueError): s.run('canary')

    def test_owned_trial_cleans_normal_and_timeout_descendants(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp)
                marker = f.auto / 'descendant-pid'
                script = ('#!' + sys.executable + '\nimport subprocess,sys,time\nfrom pathlib import Path\n'
                    + 'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\n'
                    + 'Path(' + repr(str(marker)) + ').write_text(str(p.pid))\n'
                    + ('time.sleep(30)\n' if timeout else 'print("CANARY_OK synthetic123",flush=True)\n'))
                f.cli.write_text(script)
                f.config['canary_run_budget_seconds'] = 1; f.save()
                s = f.supervisor(verifier=lambda r, sid: dict(state='completed', set_id=sid, attempt_count=3))
                if timeout:
                    with self.assertRaises(ValueError): s.run('canary')
                else: self.assertEqual(s.run('canary'), '카나리 통과 synthetic123')
                pid = int(marker.read_text())
                for _ in range(100):
                    result = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
                    if result.returncode or result.stdout.strip().startswith('Z'): break
                    time.sleep(.02)
                else: self.fail('descendant survived OwnedTrial cleanup')
                inv = next((f.auto / 'canary').glob('invocation-*'))
                end = f.m.read_json(inv / 'end.json')
                self.assertEqual(end['timed_out'], timeout)
                if timeout:
                    with self.assertRaises(ValueError): s.run('canary')

    def test_parent_kill_inherited_lock_and_ambiguous_canary_refuse_relaunch(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); marker = f.auto / 'started'
            f.cli.write_text('#!' + sys.executable + '\nimport time\nfrom pathlib import Path\nPath('
                + repr(str(marker)) + ').write_text("started")\ntime.sleep(1)\nprint("CANARY_OK synthetic123")\n')
            f.config['canary_run_budget_seconds'] = 2; f.save()
            s = f.supervisor(verifier=lambda r, sid: dict(state='completed', set_id=sid, attempt_count=3))
            pid = os.fork()
            if pid == 0:
                try: s.run('canary')
                finally: os._exit(0)
            try:
                for _ in range(150):
                    if marker.exists(): break
                    time.sleep(.02)
                self.assertTrue(marker.exists())
                os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0); pid = None
                with self.assertRaises(ValueError): s.run('canary')
                time.sleep(2.2)
                with self.assertRaises(ValueError): s.run('canary')
                self.assertEqual(len(list((f.auto / 'canary').glob('invocation-*'))), 1)
                self.assertFalse((f.auto / 'canary-receipt.json').exists())
            finally:
                if pid is not None:
                    os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)

    def test_activation_rejects_receipt_without_actual_invocation_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); f.config['activation'] = True; f.save()
            s = f.supervisor()
            f.m.immutable(f.auto / 'canary-receipt.json', f.m.encode(dict(passed=True,
                nonce='synthetic123', policy_sha256=s.policy_sha256, supervisor_sha256=f.config['supervisor_sha256'])))
            with self.assertRaises(ValueError): s.activated()

    def test_missing_invocation_end_receipt_blocks_even_pending_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); models = []
            def execute(argv, **kw):
                if '--output' in argv: f.frozen(Path(argv[argv.index('--output') + 1]))
                else:
                    models.append(argv)
                    p = Path(f.config['registry']) / '2026-11-10_synthetic_pending'
                    if not p.exists(): f.register(p.name)
                return 0, False
            s = f.activate(executor=execute, verifier=lambda r, sid: dict(state='await_plan_checkpoint', set_id=sid, attempt_count=0))
            self.assertEqual(s.run('daily'), '연구 대기 2026-11-10')
            folder = f.auto / '2026-11-10'
            for inv in folder.glob('invocation-*'):
                if f.m.read_json(inv / 'start.json')['kind'] == 'daily': (inv / 'end.json').unlink()
            self.assertEqual(s.run('continue'), '연구 차단 2026-11-10')
            self.assertEqual(len(models), 1)

    def test_legacy_completed_day_is_audited_without_model_or_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            pub = f.core / 'research' / 'legacy'; pub.mkdir(parents=True)
            priv = f.private / 'legacy'; priv.mkdir(mode=0o700)
            f.m.immutable(priv / 'unchanged.json', b'{}')
            f.config['legacy_completed'] = [dict(date='2026-11-10', public_dir=str(pub), private_dir=str(priv), audit='legacy_ema_v1')]
            f.save(); audits = []
            def audit(a, b): audits.append((a, b)); return dict(status='completed', conclusion='defer')
            s = f.activate(auditor=audit, executor=lambda *a, **k: self.fail('never acquire or model'))
            self.assertEqual(s.run('daily'), '기존 연구 확인 2026-11-10')
            self.assertEqual(s.run('daily'), '')
            self.assertEqual(len(audits), 2)
            self.assertFalse((f.auto / '2026-11-10' / 'snapshot').exists())
            self.assertEqual((priv / 'unchanged.json').read_bytes(), b'{}')

    def test_deadline_launch_count_and_wall_budget_survive_new_instances(self):
        for reason in ('deadline', 'wall', 'launches', 'interrupted'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp); s = f.activate(executor=lambda *a, **k: self.fail('budget must stop launch'))
                folder = f.m.mkdir(f.auto / '2026-11-10')
                now = s.day()
                if reason == 'wall': start = now.timestamp() - 7201
                else: start = now.timestamp()
                ledger = dict(schema_version=1, date='2026-11-10', status='running' if reason == 'interrupted' else 'pending',
                    launches=4 if reason == 'launches' else 1, acquisition_attempts=1,
                    started_epoch=start, policy_sha256=s.policy_sha256)
                s.save_ledger(folder, ledger)
                s = f.supervisor(executor=lambda *a, **k: self.fail('must not launch'))
                if reason == 'deadline': s.now = lambda: now.replace(hour=17)
                self.assertEqual(s.run('deadline' if reason == 'deadline' else 'continue'), '연구 차단 2026-11-10')
                self.assertEqual(f.m.read_json(folder / 'ledger.json')['started_epoch'], start)
                self.assertEqual(s.run('continue'), '')

    def test_duplicate_date_registries_block_before_any_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            for name in ('2026-11-10_one', '2026-11-10_two'):
                (Path(f.config['registry']) / name).mkdir(mode=0o700)
            s = f.activate(executor=lambda *a, **k: self.fail('duplicate day'))
            self.assertEqual(s.run('daily'), '연구 차단 2026-11-10')

    def test_snapshot_hash_missing_csv_and_extra_csv_are_rejected(self):
        for mutation in ('changed', 'missing', 'extra'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp); output = f.auto / 'snapshot'; f.frozen(output)
                s = f.supervisor(); s.frozen_manifest(output, '2026-11-10')
                p = next(output.glob('*.csv'))
                if mutation == 'changed': p.write_bytes(b'PRIVATE')
                elif mutation == 'missing': p.unlink()
                else: f.m.immutable(output / 'extra.csv', b'PRIVATE')
                with self.assertRaises(ValueError): s.frozen_manifest(output, '2026-11-10')

    def test_completed_repeat_reverifies_instead_of_trusting_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); count = [0]
            def execute(argv, **kw):
                if '--output' in argv: f.frozen(Path(argv[argv.index('--output') + 1]))
                else: f.register('2026-11-10_synthetic_done')
                return 0, False
            def verify(reg, sid):
                count[0] += 1
                if count[0] > 1: raise ValueError('private corruption')
                return dict(state='completed', set_id=sid, conclusion='defer', attempt_count=3)
            s = f.activate(verifier=verify, executor=execute)
            # Publication proof is exercised separately with real Git blobs/PR reads.
            s.verify_publication = lambda *a: True
            self.assertEqual(s.run('daily'), '연구 완료 2026-11-10_synthetic_done defer')
            self.assertEqual(s.run('daily'), '연구 차단 2026-11-10')
            self.assertEqual(count[0], 2)

    def test_pending_ledger_edit_is_detected_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            s = f.activate(executor=lambda *a, **k: self.fail('must not launch'))
            folder = f.m.mkdir(f.auto / '2026-11-10')
            ledger = dict(schema_version=1, date='2026-11-10', status='pending', launches=4,
                acquisition_attempts=1, started_epoch=s.day().timestamp(), policy_sha256=s.policy_sha256)
            s.save_ledger(folder, ledger)
            ledger['launches'] = 0
            f.m.atomic(folder / 'ledger.json', ledger)
            with self.assertRaises(ValueError): s.run('continue')

    def test_cli_help_and_error_stdout_are_status_only(self):
        result = subprocess.run([sys.executable, str(SOURCE), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('--config', result.stdout); self.assertIn('deadline', result.stdout)
        result = subprocess.run([sys.executable, str(SOURCE), '--config', '/nonexistent/SECRET', '--mode', 'daily'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '자동화 차단\n')
        self.assertEqual(result.stderr, '')

    def test_weekly_requires_private_actual_receipt_and_is_once_per_week(self):
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp); calls = []
                git(f.core, 'remote', 'add', 'origin', 'https://github.com/seanjeonn/sh-quant.git')
                def execute(argv, **kw):
                    calls.append(argv)
                    if valid:
                        receipt = f.auto / 'week-2026-W46' / 'weekly-review.json'
                        f.m.immutable(receipt, f.m.encode(dict(schema_version=1, completed=True,
                            reviewed_at='2026-11-10T15:00:00+09:00',
                            managed_issue_urls=['https://github.com/seanjeonn/sh-quant/issues/33'],
                            managed_issue_body_sha256={'https://github.com/seanjeonn/sh-quant/issues/33':f.m.sha(b'reviewed') })))
                    kw['stdout'].write(b'completed=true SECRET not a receipt')
                    return 0, False
                s = f.activate(executor=execute)
                s.github_reader = lambda *a: dict(number=33,url='https://github.com/seanjeonn/sh-quant/issues/33',body='reviewed',state='OPEN')
                expected = '주간 검토 완료 1' if valid else '주간 검토 차단'
                self.assertEqual(s.run('weekly'), expected)
                self.assertEqual(s.run('weekly'), '')
                self.assertEqual(len(calls), 1)
                self.assertIn('40', calls[0]); self.assertIn('900', calls[0])

    def test_daily_pending_continue_verified_completion_and_date_uniqueness(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); calls = []; state = ['await_plan_checkpoint']
            def execute(argv, **kw):
                calls.append(argv)
                if '--output' in argv:
                    f.frozen(Path(argv[argv.index('--output') + 1]))
                else:
                    root = Path(f.config['registry']) / '2026-11-10_synthetic_daily'
                    if not root.exists(): f.register(root.name)
                    else: state[0] = 'completed'
                    kw['stdout'].write(b'RAW METRICS NOT PROOF')
                return 0, False
            def verify(reg, sid):
                return dict(state=state[0], attempt_count=3, set_id=sid, conclusion='defer')
            s = f.activate(executor=execute, verifier=verify)
            s.verify_publication = lambda *a: True  # isolated lifecycle test; proof tests above
            self.assertEqual(s.run('daily'), '연구 대기 2026-11-10')
            self.assertEqual(s.run('continue'), '연구 완료 2026-11-10_synthetic_daily defer')
            ledger = f.m.read_json(f.auto / '2026-11-10' / 'ledger.json')
            self.assertEqual(ledger['launches'], 2)
            self.assertEqual(ledger['acquisition_attempts'], 1)
            self.assertEqual(s.run('daily'), '')
            self.assertEqual(len(calls), 3)
            self.assertIn('--skills', calls[-1])
            wt = Path(f.config['workspace_root']) / '2026-11-10'
            self.assertEqual(git(wt, 'branch', '--show-current'), 'research/2026-11-10_daily')
            for n in f.config['code_pins']:
                self.assertEqual(f.m.sha((wt / n).read_bytes()), f.config['code_pins'][n])

    def test_partial_acquisition_is_charged_once_and_never_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); calls = []
            def partial(argv, **kw):
                calls.append(argv)
                out = Path(argv[argv.index('--output') + 1]); out.mkdir(mode=0o700)
                f.m.immutable(out / 'partial.json', b'{}')
                kw['stdout'].write(b'403 PRIVATE PROVIDER ERROR')
                return 1, False
            s = f.activate(executor=partial)
            self.assertEqual(s.run('daily'), '연구 차단 2026-11-10')
            self.assertEqual(len(calls), 1)
            ledger = f.m.read_json(f.auto / '2026-11-10' / 'ledger.json')
            self.assertEqual(ledger['status'], 'blocked')
            self.assertEqual(ledger['acquisition_attempts'], 1)
            self.assertEqual(s.run('daily'), '')
            self.assertEqual(s.run('continue'), '')
            self.assertEqual(len(calls), 1)
            self.assertIn('--max-minutes', calls[0]); self.assertIn('20', calls[0])

    def test_canary_readonly_evidence_redaction_and_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp); calls = []
            def verify(reg, sid):
                return {'state': 'completed', 'attempt_count': 3, 'conclusion': 'defer', 'set_id': sid}
            def execute(argv, *, cwd, timeout, stdout, stderr, pass_fds, env):
                calls.append(argv)
                stdout.write(b'secret raw metrics 123\nCANARY_OK synthetic123\n')
                stderr.write(b'provider secret')
                return 0, False
            s = f.supervisor(executor=execute, verifier=verify)
            self.assertEqual(s.run('canary'), '카나리 통과 synthetic123')
            receipt = f.m.read_json(f.auto / 'canary-receipt.json')
            self.assertTrue(receipt['passed']); self.assertEqual(receipt['attempt_count'], 3)
            self.assertEqual(len(calls), 1)
            self.assertIn('--max-turns', calls[0]); self.assertIn('8', calls[0])
            self.assertNotIn('--yolo', calls[0])
            self.assertEqual(s.run('canary'), '')
            f.config['activation'] = True; f.save(); f.supervisor().activated()
            f.config['daily_max_turns'] = 79; f.save()
            with self.assertRaises(ValueError): f.supervisor().activated()

    def test_policy_activation_and_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            s = f.supervisor()
            self.assertEqual(s.run('continue'), '')
            with self.assertRaises(ValueError): s.run('daily')
            original = s.policy_sha256
            f.config['activation'] = True; f.save()
            self.assertEqual(f.supervisor().policy_sha256, original)
            with self.assertRaises(ValueError): f.supervisor().activated()
            self.assertEqual(f.supervisor().run('daily'), '연구 차단 2026-11-10')
            f.binary.write_text('drift')
            with self.assertRaises(ValueError): f.supervisor()

    def test_private_files_reject_links_permissions_and_overwrite(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); root.chmod(0o700)
            p = root / 'state.json'
            m.immutable(p, m.encode({'a': 1}))
            self.assertEqual(m.read_json(p), {'a': 1})
            with self.assertRaises((ValueError, FileExistsError)):
                m.immutable(p, b'overwrite')
            p.chmod(0o644)
            with self.assertRaises(ValueError): m.private(p)
            p.chmod(0o600)
            os.link(p, root / 'hard')
            with self.assertRaises(ValueError): m.private(p)
            (root / 'sym').symlink_to(p)
            with self.assertRaises(ValueError): m.private(root / 'sym')

    def test_strict_json_rejects_duplicate_and_nonfinite(self):
        self.assertTrue(SOURCE.exists(), 'supervisor implementation missing')
        m = module()
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError):
                m.decode(raw)
        self.assertEqual(m.decode('{"x":1}'), {'x': 1})


if __name__ == '__main__':
    unittest.main()
