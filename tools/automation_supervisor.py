#!/usr/bin/env python3
"""Bounded investops supervisor (#33). Private evidence, status-only stdout.

This is a process/deadline and evidence boundary, not an agent sandbox. A model
with tools can violate its prompt; code drift is detected, not prevented.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import uuid
from zoneinfo import ZoneInfo


class Blocked(ValueError):
    pass


def require(ok):
    if not ok:
        raise Blocked('blocked')


def decode(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result)
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: require(False))


def encode(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False,
                       separators=(',', ':')) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def path(value, directory=False, missing=False):
    p = Path(value)
    require(p.is_absolute() and '..' not in p.parts and str(p) == str(p.resolve()))
    for q in (p, *p.parents):
        require(not q.is_symlink())
    if p.exists():
        s = p.stat()
        require(s.st_uid == os.getuid())
        require(stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode))
        if not directory: require(s.st_nlink == 1)
    else: require(missing)
    return p


def private(value, directory=False, missing=False):
    p = path(value, directory, missing)
    require(not any((q / '.git').exists() for q in (p, *p.parents)))
    if p.exists():
        require(stat.S_IMODE(p.stat().st_mode) == (0o700 if directory else 0o600))
    require(p.parent.stat().st_uid == os.getuid() and
            stat.S_IMODE(p.parent.stat().st_mode) == 0o700)
    return p


def sync_dir(p):
    fd = os.open(p, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def immutable(p, raw):
    p = private(p, missing=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    sync_dir(p.parent)


def read_json(p):
    return decode(private(p).read_bytes())


def mkdir(p):
    p = private(p, directory=True, missing=True)
    if not p.exists():
        try: p.mkdir(mode=0o700)
        except FileExistsError: private(p, directory=True)
        sync_dir(p.parent)
    return p


def atomic(p, value):
    p = private(p, missing=True)
    tmp = p.with_name('.' + p.name + '-' + uuid.uuid4().hex)
    immutable(tmp, encode(value))
    os.replace(tmp, p); sync_dir(p.parent)


LIMITS = {'daily_max_launches': 4, 'daily_max_turns': 80,
          'daily_run_budget_seconds': 1800, 'daily_wall_seconds': 7200,
          'weekly_max_turns': 40, 'weekly_run_budget_seconds': 900,
          'canary_max_turns': 8, 'canary_run_budget_seconds': 120,
          'acquisition_max_attempts': 600, 'acquisition_max_minutes': 20}
PATHS = {'profile_home', 'repo', 'core_repo', 'binary', 'hermes_executable',
         'private_root', 'registry', 'workspace_root', 'env_file', 'token_file'}
FIELDS = PATHS | set(LIMITS) | {'schema_version', 'engine_commit', 'binary_sha256',
         'supervisor_sha256', 'code_pins', 'daily_start', 'deadline', 'timezone',
         'min_interval', 'activation', 'canary'}


MODES = ('canary', 'daily', 'continue', 'weekly', 'deadline', 'publication')
STAGES = ('arguments', 'config_validation', 'pin_validation', 'canary_validation',
          'ready', 'preflight', 'lock', 'daily', 'weekly', 'canary', 'publication')
REASONS = set(STAGES) | {'lock_busy', 'idle_continue', 'missing_day_deadline',
                             'ok', 'preledger_failure_manual_only'}


class Supervisor:
    def diagnostic_root(self):
        if hasattr(self, '_trusted_root'):
            return private(self._trusted_root, directory=True)
        # No config-controlled fallback on constructor failure. In particular,
        # invalid profile/private_root values must never redirect a write.
        profile = path(os.environ['HERMES_HOME'], directory=True)
        require(profile.parts[-2:] == ('profiles', 'investops'))
        private(profile / 'private', directory=True)
        return private(profile / 'private' / 'automation', directory=True)

    def diagnostic(self, mode, outcome, reason):
        require(outcome in ('started', 'blocked', 'quiet', 'ok') and reason in REASONS)
        folder = mkdir(self.diagnostic_root() / 'diagnostics')
        now = self.day() if hasattr(self, 'now') else dt.datetime.now(ZoneInfo('Asia/Seoul'))
        stage = getattr(self, 'stage', 'arguments')
        require(stage in STAGES)
        immutable(folder / (uuid.uuid4().hex + '.json'), encode(dict(
            schema_version=1, mode=mode if mode in MODES else 'unknown',
            date=now.date().isoformat(), stage=stage, outcome=outcome,
            reason=reason, timestamp=now.timestamp())))
        self._diagnosed = True

    def __init__(self, config, *, now=None, executor=None, verifier=None, auditor=None):
        self.stage = 'config_validation'
        self.config_path = str(private(config))
        self.c = c = read_json(config)
        require(isinstance(c, dict) and FIELDS <= c.keys() and not c.keys() - FIELDS - {'legacy_completed', 'canary_generation', 'expanded_data'})
        if 'canary_generation' in c:
            require(type(c['canary_generation']) is str and re.fullmatch('[A-Za-z0-9_-]{8,100}', c['canary_generation']))
        require(type(c['schema_version']) is int and c['schema_version'] == 1)
        require(type(c['activation']) is bool)
        for name, maximum in LIMITS.items():
            require(type(c[name]) is int and 0 < c[name] <= maximum)
        require(type(c['min_interval']) in (int, float) and math.isfinite(c['min_interval']) and c['min_interval'] >= .25)
        require(c['daily_start'] == '14:30' and c['deadline'] == '17:00' and c['timezone'] == 'Asia/Seoul')
        require(c['acquisition_max_minutes'] * 60 + c['daily_run_budget_seconds'] < 3600)
        for name in PATHS: require(type(c[name]) is str and Path(c[name]).is_absolute())
        profile = path(c['profile_home'], directory=True)
        require(profile.parts[-2:] == ('profiles', 'investops'))
        if 'HERMES_HOME' in os.environ:
            require(Path(os.environ['HERMES_HOME']).resolve() == profile)
        self.root = private(c['private_root'], directory=True)
        require(self.root.is_relative_to(profile))
        require(Path(config).resolve().is_relative_to(profile))
        require(Path(c['registry']).is_relative_to(self.root))
        require(Path(c['workspace_root']) == profile / 'workspaces' / 'sh-quant-auto')
        require(Path(c['env_file']) == profile / '.env')
        require(Path(c['token_file']).is_relative_to(profile / 'private'))
        private(c['registry'], directory=True)
        for name in ('env_file', 'token_file'): private(c[name], missing=True)
        path(c['workspace_root'], directory=True, missing=True)
        for name in ('repo', 'core_repo'): path(c[name], directory=True)
        for name in ('binary', 'hermes_executable'): path(c[name])
        require(os.access(c['hermes_executable'], os.X_OK))
        for name, size in (('engine_commit', 40), ('binary_sha256', 64), ('supervisor_sha256', 64)):
            require(type(c[name]) is str and re.fullmatch('[a-f0-9]{' + str(size) + '}', c[name]))
        can = c['canary']
        require(type(can) is dict and set(can) == {'registry', 'set_id', 'nonce'})
        private(can['registry'], directory=True)
        # Canary is read-only and can reuse an already verified synthetic
        # registry elsewhere in THIS profile's private tree. Never migrate or
        # rewrite its immutable historical commands just to relocate evidence.
        require(Path(can['registry']).is_relative_to(profile / 'private'))
        require(re.fullmatch(r'\d{4}-\d{2}-\d{2}_synthetic[a-z0-9_-]*', can['set_id']))
        require(type(can['nonce']) is str and re.fullmatch('[A-Za-z0-9_-]{8,100}', can['nonce']))
        require(type(c['code_pins']) is dict and c['code_pins'])
        for name, digest in c['code_pins'].items():
            require(type(name) is str and not Path(name).is_absolute() and '..' not in Path(name).parts)
            require(type(digest) is str and re.fullmatch('[a-f0-9]{64}', digest))
        require({'tools/research_set.py', 'tools/research_contract.py', 'tools/prepare_toss.py', 'Cargo.toml', 'Cargo.lock'} <= c['code_pins'].keys())
        require(any(n.startswith('src/') for n in c['code_pins']))
        if 'expanded_data' in c:
            expanded = c['expanded_data']
            require(type(expanded) is dict and set(expanded) == {'universe_file', 'universe_sha256',
                'seed_manifest', 'seed_manifest_sha256', 'start_date', 'refresh_policy'})
            require(all(type(v) is str for v in expanded.values()))
            require(expanded['start_date'] == '2000-01-01' and
                    expanded['refresh_policy'] == 'overlap200_prefix_carried_v1')
            for key in ('universe_sha256', 'seed_manifest_sha256'):
                require(re.fullmatch('[a-f0-9]{64}', expanded[key]))
            catalog = path(expanded['universe_file'])
            require(catalog.is_relative_to(Path(c['core_repo']) / 'universes'))
            catalog_name = str(catalog.relative_to(c['core_repo']))
            require({'tools/refresh_toss.py', 'tools/universe_contract.py', 'tools/collect_universe.py',
                     catalog_name} <= c['code_pins'].keys())
            require(c['code_pins'][catalog_name] == expanded['universe_sha256'] == sha(catalog.read_bytes()))
            seed = private(expanded['seed_manifest'])
            require(seed.name == 'manifest.json' and seed.is_relative_to(profile / 'private'))
            require(self.root.is_relative_to(profile / 'private'))
            require(sha(seed.read_bytes()) == expanded['seed_manifest_sha256'])
        legacy = c.get('legacy_completed', [])
        require(type(legacy) is list)
        dates = set()
        for item in legacy:
            require(type(item) is dict and set(item) == {'date', 'public_dir', 'private_dir', 'audit'})
            require(item['audit'] == 'legacy_ema_v1' and dt.date.fromisoformat(item['date']).isoformat() == item['date'])
            require(item['date'] not in dates); dates.add(item['date'])
            require(Path(item['public_dir']).is_relative_to(Path(c['core_repo']) / 'research'))
            require(Path(item['private_dir']).is_relative_to(profile / 'private'))
            path(item['public_dir'], directory=True); private(item['private_dir'], directory=True)
        self.policy_sha256 = sha(encode({k: v for k, v in c.items() if k != 'activation'}))
        self.now = now or (lambda: dt.datetime.now(ZoneInfo('Asia/Seoul')))
        self.executor = executor
        self.verifier = verifier
        self.auditor = auditor
        self._policy_root = private(profile / 'private' / 'automation', directory=True)
        self._trusted_root = self.root
        self.stage = 'pin_validation'
        self.check_pins()
        if 'expanded_data' in c:
            self.expanded_manifest(Path(c['expanded_data']['seed_manifest']),
                                   c['expanded_data']['seed_manifest_sha256'])
        self.stage = 'ready'

    def git(self, repo, *args):
        return self.git_bytes(repo, *args).decode().strip()

    def git_bytes(self, repo, *args):
        result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=30,
                                env={'PATH': os.defpath, 'HOME': str(Path.home()), 'GIT_TERMINAL_PROMPT': '0',
                                     'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
        require(result.returncode == 0)
        return result.stdout

    def check_pins(self, worktree=None):
        c = self.c
        require(sha(Path(__file__).read_bytes()) == c['supervisor_sha256'])
        require(sha(path(c['binary']).read_bytes()) == c['binary_sha256'])
        require(self.git(c['core_repo'], 'rev-parse', 'HEAD') == c['engine_commit'])
        for repo in {c['core_repo'], c['repo'], str(worktree or c['core_repo'])}:
            for name, digest in c['code_pins'].items():
                require(sha(path(Path(repo) / name).read_bytes()) == digest)
            actual = set()
            for base in ('src', 'tools', '.cargo'):
                folder = Path(repo) / base
                if folder.exists():
                    for p in folder.rglob('*'):
                        if '__pycache__' not in p.parts and p.suffix != '.pyc' and (p.is_file() or p.is_symlink()):
                            name = str(p.relative_to(repo))
                            if name != 'tools/automation_supervisor.py': actual.add(name)
            for name in ('Cargo.toml', 'Cargo.lock', 'build.rs', 'rust-toolchain', 'rust-toolchain.toml'):
                if (Path(repo) / name).exists(): actual.add(name)
            if 'expanded_data' in c:
                actual.add(str(Path(c['expanded_data']['universe_file']).relative_to(c['core_repo'])))
            require(actual == set(c['code_pins']))

    def canary_paths(self):
        generation = self.c.get('canary_generation')
        if generation is None:
            return self.root / 'canary-receipt.json', self.root / 'canary'
        folder = self.root / 'canaries' / generation
        return folder / 'receipt.json', folder

    def validate_canary_receipt(self):
        receiptpath, folder = self.canary_paths()
        receipt = read_json(receiptpath)
        require(set(receipt) == {'schema_version', 'passed', 'nonce', 'policy_sha256', 'supervisor_sha256',
                                'runner_state', 'attempt_count', 'verified_at', 'invocation'})
        require(type(receipt['schema_version']) is int and receipt['schema_version'] == 1)
        require(receipt['passed'] is True and receipt['nonce'] == self.c['canary']['nonce'] and
                receipt['policy_sha256'] == self.policy_sha256 and receipt['supervisor_sha256'] == self.c['supervisor_sha256'])
        require(receipt['runner_state'] == 'completed' and type(receipt['attempt_count']) is int and receipt['attempt_count'] >= 0)
        require(type(receipt['invocation']) is str and re.fullmatch('invocation-[a-f0-9]{32}', receipt['invocation']))
        inv = private(folder / receipt['invocation'], directory=True)
        start = read_json(inv / 'start.json'); end = read_json(inv / 'end.json')
        require(start['kind'] == 'canary' and start['policy_sha256'] == self.policy_sha256)
        require(type(end['exit_code']) is int and end['exit_code'] == 0 and end['timed_out'] is False)
        require(start['started_at'] <= end['ended_at'] <= receipt['verified_at'])
        for stream in ('stdout', 'stderr'):
            require(sha(private(inv / (stream + '.log')).read_bytes()) == end[stream + '_sha256'])
        require(('CANARY_OK ' + receipt['nonce']) in private(inv / 'stdout.log').read_text().splitlines())
        return receipt

    def activated(self):
        self.stage = 'canary_validation'
        require(self.c['activation'])
        self.validate_canary_receipt()

    def core_module(self, name):
        self.check_pins()
        spec = importlib.util.spec_from_file_location('_supervisor_' + name, Path(self.c['core_repo']) / 'tools' / (name + '.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def verify(self, registry, set_id):
        if self.verifier is not None:
            return self.verifier(registry, set_id)
        # research_set.contract resolves a sibling import. Load the pinned module,
        # never one supplied by the research worktree or cwd.
        sys.modules['research_contract'] = self.core_module('research_contract')
        with self.core_module('research_set').Runner(registry, set_id) as runner:
            return runner.verify()

    def launch(self, folder, kind, command, cwd, timeout):
        if kind in ('daily', 'continue', 'acquisition'):
            deadline = self.day().replace(hour=17, minute=0, second=0, microsecond=0)
            timeout = min(timeout, deadline.timestamp() - self.day().timestamp())
        require(timeout > 0)
        inv = mkdir(folder / ('invocation-' + uuid.uuid4().hex))
        scopefile = inv / 'scope.json'
        immutable(scopefile, encode(dict(schema_version=1, expires_at=time.time() + timeout, token=uuid.uuid4().hex)))
        scope = (str(scopefile), sha(private(scopefile).read_bytes()))
        atomic(folder / 'active-scope.json', dict(path=scope[0], sha256=scope[1]))
        env = dict(os.environ, HERMES_HOME=self.c['profile_home'], PYTHONDONTWRITEBYTECODE='1',
                   INVESTOPS_SCOPE_POINTER=str(folder / 'active-scope.json'),
                   INVESTOPS_SCOPE_FILE=scope[0], INVESTOPS_SCOPE_SHA256=scope[1])
        begin = {'schema_version': 1, 'kind': kind, 'started_at': self.now().timestamp(),
                 'command': command, 'timeout': timeout, 'cwd': str(cwd),
                 'policy_sha256': self.policy_sha256}
        immutable(inv / 'start.json', encode(begin))
        for name in ('stdout.log', 'stderr.log'): immutable(inv / name, b'')
        rc = None; timed_out = False
        try:
            with open(private(inv / 'stdout.log'), 'ab', buffering=0) as out, open(private(inv / 'stderr.log'), 'ab', buffering=0) as err:
                if self.executor is not None:
                    rc, timed_out = self.executor(command, cwd=str(cwd), timeout=timeout,
                                                 stdout=out, stderr=err, pass_fds=(self.lock_fd,), env=env)
                else:
                    trial = self.core_module('research_set').OwnedTrial(
                        subprocess.Popen, command, cwd=str(cwd), timeout=timeout,
                        stdout=out, stderr=err, pass_fds=(self.lock_fd,),
                        env=env, execution_scope=scope, revoke_scope=True)
                    try:
                        rc = trial.wait(); timed_out = trial.timed_out
                    except BaseException:
                        trial.stop(); raise
                os.fsync(out.fileno()); os.fsync(err.fileno())
        finally:
            if not (inv / 'cancelled').exists():
                immutable(inv / 'cancelled', encode(dict(schema_version=1)))
            immutable(inv / 'end.json', encode({'schema_version': 1, 'exit_code': rc,
                'timed_out': timed_out, 'ended_at': self.now().timestamp(),
                'stdout_sha256': sha(private(inv / 'stdout.log').read_bytes()),
                'stderr_sha256': sha(private(inv / 'stderr.log').read_bytes())}))
        require(type(rc) is int and rc == 0 and timed_out is False)
        if kind != 'acquisition':
            # CLI versions can report provider failures while exiting zero. This
            # deliberately conservative deny pattern may block a quoted 403 too;
            # it never turns output into completion evidence.
            for name in ('stdout.log', 'stderr.log'):
                raw = private(inv / name).read_bytes()
                require(re.search(rb'(?i)(?:\b403\b|\bforbidden\b|\b(?:provider|authentication|api)[ _-]+error\b)', raw) is None)
        return inv

    def agent(self, folder, mode, prompt, cwd, budget=None):
        promptfile = folder / ('prompt-' + uuid.uuid4().hex + '.txt')
        immutable(promptfile, prompt.encode())
        prefix = 'daily' if mode == 'continue' else mode
        limit = self.c[prefix + '_run_budget_seconds']
        if budget is not None: limit = min(limit, int(budget))
        require(limit > 0)
        argv = [self.c['hermes_executable'], 'chat', '--oneshot', '-Q',
                '--max-turns', str(self.c[prefix + '_max_turns']), '--run-budget', str(limit),
                '--in', str(cwd), '--query-file', str(promptfile)]
        if mode != 'canary': argv += ['--skills', 'sh-quant-automation']
        return self.launch(folder, mode, argv, cwd, limit)

    def canary(self):
        receiptpath, folder = self.canary_paths()
        if receiptpath.exists():
            self.validate_canary_receipt()
            return ''
        if 'canary_generation' in self.c:
            parent = private(folder.parent, directory=True, missing=True)
            if not parent.exists(): mkdir(parent)
        require(not folder.exists())  # an interrupted/failed canary needs operator review
        mkdir(folder)
        can = self.c['canary']
        before = self.verify(can['registry'], can['set_id'])
        require(before['state'] == 'completed')
        prompt = ('Read-only synthetic CLI probe. Do not execute tools, prepare, trials, market APIs, '
                  'credentials, Git or any writes. Reply with exactly this line:\nCANARY_OK ' + can['nonce'])
        inv = self.agent(folder, 'canary', prompt, self.c['repo'])
        after = self.verify(can['registry'], can['set_id'])
        require(before == after)
        raw = private(inv / 'stdout.log').read_text()
        require(('CANARY_OK ' + can['nonce']) in raw.splitlines())
        receipt = {'schema_version': 1, 'passed': True, 'nonce': can['nonce'],
                   'policy_sha256': self.policy_sha256, 'supervisor_sha256': self.c['supervisor_sha256'],
                   'runner_state': after['state'], 'attempt_count': after['attempt_count'],
                   'verified_at': self.now().timestamp(), 'invocation': inv.name}
        immutable(receiptpath, encode(receipt))
        return '카나리 통과 ' + can['nonce']

    def day(self):
        now = self.now()
        require(now.tzinfo is not None)
        return now.astimezone(ZoneInfo('Asia/Seoul'))

    def read_ledger(self, folder):
        ledger = read_json(folder / 'ledger.json')
        require(type(ledger) is dict and type(ledger.get('revision')) is int and 0 <= ledger['revision'] < 10000)
        snapshots = sorted(folder.glob('ledger-[0-9][0-9][0-9][0-9].json'))
        require(len(snapshots) == ledger['revision'] + 1)
        previous = None
        for index, snapshot in enumerate(snapshots):
            require(snapshot.name == 'ledger-%04d.json' % index)
            item = read_json(snapshot)
            require(item['revision'] == index and item['schema_version'] == 1)
            require(item['date'] == folder.name and item['policy_sha256'] == self.policy_sha256)
            require(type(item['launches']) is int and 0 <= item['launches'] <= self.c['daily_max_launches'])
            require(type(item['acquisition_attempts']) is int and 0 <= item['acquisition_attempts'] <= 1)
            require(item['status'] in ('initializing', 'acquiring', 'running', 'pending', 'publication_pending', 'completed', 'legacy_completed', 'blocked'))
            require(type(item['started_epoch']) in (int, float) and math.isfinite(item['started_epoch']))
            require(item['updated_epoch'] >= item['started_epoch'])
            if previous:
                if 'expanded_data' in self.c:
                    for key in ('snapshot_sha256', 'base_manifest', 'base_manifest_sha256'):
                        if key in previous: require(item.get(key) == previous[key])
                require(item['started_epoch'] == previous['started_epoch'] and item['launches'] >= previous['launches'] and
                        item['acquisition_attempts'] >= previous['acquisition_attempts'] and item['updated_epoch'] >= previous['updated_epoch'])
            previous = item
        require(previous == ledger)
        return ledger

    def save_ledger(self, folder, ledger):
        ledger['updated_epoch'] = self.day().timestamp()
        ledger['revision'] = ledger.get('revision', -1) + 1
        immutable(folder / ('ledger-%04d.json' % ledger['revision']), encode(ledger))
        atomic(folder / 'ledger.json', ledger)

    def block(self, folder, ledger):
        ledger['status'] = 'blocked'
        self.save_ledger(folder, ledger)
        return '연구 차단 ' + ledger['date']

    def day_sets(self, date):
        registry = private(self.c['registry'], directory=True)
        sets = []
        for p in registry.iterdir():
            if p.name.startswith(date + '_'):
                require(re.fullmatch(re.escape(date) + r'_[a-z0-9][a-z0-9_-]{0,63}', p.name))
                private(p, directory=True); sets.append(p.name)
        require(len(sets) <= 1)
        return [self.bound_verify(date, sid) for sid in sets]

    def bound_verify(self, date, sid):
        folder = self.root / date
        manifest, digest = self.frozen_manifest(folder / 'snapshot', date)
        worktree = self.worktree(date)
        sys.modules['research_contract'] = self.core_module('research_contract')
        with self.core_module('research_set').Runner(self.c['registry'], sid) as runner:
            c, plan = runner.config, runner.plan
            require(c['manifest'] == str(manifest) and c['manifest_sha256'] == digest)
            require(plan['data_manifest_sha256'] == digest)
            require(c['binary'] == self.c['binary'] and c['binary_sha256'] == self.c['binary_sha256'])
            require(plan['binary_sha256'] == self.c['binary_sha256'] and plan['engine_commit'] == self.c['engine_commit'])
            require(c['repo'] == str(worktree) and c['plan_source'] == str(folder / 'plan.json'))
            require(plan['schema_version'] == 2 and plan['set_id'] == sid)
            require(plan.get('supervisor_scope') == str(folder / 'active-scope.json'))
            return self.verifier(self.c['registry'], sid) if self.verifier is not None else runner.verify()

    def remaining(self, ledger):
        now = self.day()
        elapsed = now.timestamp() - ledger['started_epoch']
        require(elapsed >= 0)
        deadline = now.replace(hour=17, minute=0, second=0, microsecond=0)
        return min(self.c['daily_wall_seconds'] - elapsed, deadline.timestamp() - now.timestamp())

    def select_base(self, date):
        """Newest same-policy completed data wins, including failed research days."""
        require(dt.date.fromisoformat(date).isoformat() == date)
        for folder in sorted(self.root.iterdir(), reverse=True):
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', folder.name) or folder.name >= date:
                continue
            require(dt.date.fromisoformat(folder.name).isoformat() == folder.name)
            private(folder, directory=True)
            ledgerpath = private(folder / 'ledger.json', missing=True)
            if not ledgerpath.exists(): continue  # preserved interrupted preledger day
            hint = read_json(ledgerpath)
            if hint.get('policy_sha256') != self.policy_sha256: continue
            ledger = self.read_ledger(folder)
            manifest = folder / 'snapshot' / 'manifest.json'
            if 'snapshot_sha256' not in ledger:
                # Partial acquisitions are not reusable; an unbound COMPLETE one
                # is ambiguous, not permission to revert to an older vintage.
                if manifest.exists(): require(read_json(manifest).get('status') != 'complete')
                continue
            require(ledger['acquisition_attempts'] == 1)
            return self.expanded_manifest(manifest, ledger['snapshot_sha256'], folder.name)
        expanded = self.c['expanded_data']
        manifest, digest = self.expanded_manifest(Path(expanded['seed_manifest']), expanded['seed_manifest_sha256'])
        require(read_json(manifest)['cutoff_exclusive'] < date)
        return manifest, digest

    def expanded_manifest(self, manifestpath, digest=None, date=None):
        """Validate exact catalog cohort and private schema3 data, without auth reads."""
        expanded = self.c['expanded_data']
        manifestpath = private(manifestpath)
        require(manifestpath.name == 'manifest.json' and
                manifestpath.is_relative_to(Path(self.c['profile_home']) / 'private'))
        raw = manifestpath.read_bytes()
        if digest is not None:
            require(type(digest) is str and re.fullmatch('[a-f0-9]{64}', digest) and sha(raw) == digest)
        catalograw = path(expanded['universe_file']).read_bytes()
        require(sha(catalograw) == expanded['universe_sha256'])
        catalog = self.core_module('universe_contract').validate_universe(catalograw)
        require({i['market'] for i in catalog['instruments']} == {'US', 'KR'})
        value = decode(raw)
        cutoff = value.get('cutoff_exclusive')
        require(type(cutoff) is str and dt.date.fromisoformat(cutoff).isoformat() == cutoff)
        if date is not None: require(cutoff == date)
        # The pinned collector validator supports both batched seed paths and
        # ordinary refresh CSVs, checking identity, bytes, OHLCV and split coverage.
        collector = self.core_module('collect_universe')
        try:
            collector.validate_batch(manifestpath.parent, catalograw,
                dict(start_date=expanded['start_date'], cutoff_exclusive=cutoff),
                value.get('http_attempts'))  # historical seed count, not a new request budget
        except Exception:
            raise Blocked('blocked') from None
        require(private(manifestpath).read_bytes() == raw)
        return manifestpath, sha(raw)

    def frozen_manifest(self, snapshot, date):
        if 'expanded_data' in self.c:
            return self.expanded_manifest(snapshot / 'manifest.json', date=date)
        private(snapshot, directory=True)
        manifestpath = snapshot / 'manifest.json'
        manifest = read_json(manifestpath)
        require(manifest.get('schema_version') == 2 and manifest.get('provider') == 'toss' and
                manifest.get('status') == 'complete' and manifest.get('adjusted') is True and
                manifest.get('timezone') == 'Asia/Seoul' and manifest.get('cutoff_exclusive') == date)
        entries = manifest.get('entries')
        require(type(entries) is list and len(entries) == 24)
        universe = self.core_module('prepare_toss').UNIVERSE
        expected = {(market, ticker) for market, tickers in universe.items() for ticker in tickers}
        require({(e['market'], e['ticker']) for e in entries} == expected)
        filenames = set()
        for entry in entries:
            name = entry['path']
            require(type(name) is str and Path(name).name == name and name.endswith('.csv') and name not in filenames)
            filenames.add(name)
            raw = private(snapshot / name).read_bytes()
            require(sha(raw) == entry['sha256'] and raw.startswith(b'date,open,high,low,close,volume\n'))
        require({p.name for p in snapshot.glob('*.csv')} == filenames)
        return manifestpath, sha(private(manifestpath).read_bytes())

    def worktree(self, date):
        root = path(self.c['workspace_root'], directory=True, missing=True)
        if not root.exists(): root.mkdir(mode=0o700); sync_dir(root.parent)
        target = path(root / date, directory=True, missing=True)
        branch = 'research/' + date + '_daily'
        if not target.exists():
            self.git(self.c['core_repo'], '-c', 'core.hooksPath=/dev/null', 'worktree', 'add',
                     '-b', branch, str(target), self.c['engine_commit'])
        require(self.git(target, 'rev-parse', '--show-toplevel') == str(target))
        require(self.git(target, 'branch', '--show-current') == branch)
        # Research commits may advance HEAD; the root must retain the pinned ancestor.
        self.git(target, 'merge-base', '--is-ancestor', self.c['engine_commit'], 'HEAD')
        require(self.git(target, 'rev-parse', self.c['engine_commit'] + '^{commit}') == self.c['engine_commit'])
        self.check_pins(target)
        return target

    def publication_descriptor(self, folder, status):
        require(status['state'] == 'completed' and status['conclusion'] in ('accept', 'defer', 'reject'))
        require(type(status['attempt_count']) is int and status['attempt_count'] >= 0)
        sid = status['set_id']
        require(re.fullmatch(re.escape(folder.name) + r'_[a-z0-9][a-z0-9_-]{0,63}', sid))
        registered = private(Path(self.c['registry']) / sid, directory=True)
        raw = encode(dict(schema_version=1, set_id=sid, status='completed', conclusion=status['conclusion'],
            attempt_count=status['attempt_count'],
            private_report_sha256=sha(private(registered / 'report.json').read_bytes()),
            evaluation_sha256=sha(private(registered / 'evaluation.json').read_bytes()),
            engine_commit=self.c['engine_commit'],
            data_manifest_sha256=self.frozen_manifest(folder / 'snapshot', folder.name)[1],
            holdout_status='exposed', limitations=['OOS exposed; not independent validation',
                'Finite preregistered comparison only; not live-trading approval']))
        target = folder / 'publication-descriptor.json'
        if target.exists(): require(private(target).read_bytes() == raw)
        else: immutable(target, raw)
        return raw

    def publication(self):
        # Intentionally no global worker lock: the running agent's parent holds it.
        self.check_pins(); self.activated()
        date = self.day().date().isoformat(); folder = self.root / date
        ledger = self.read_ledger(folder)
        require(ledger['status'] in ('running', 'pending', 'publication_pending', 'completed'))
        states = self.day_sets(date)
        require(len(states) == 1)
        return self.publication_descriptor(folder, states[0])

    def verify_publication(self, folder, status):
        raw = self.publication_descriptor(folder, status)
        receiptpath = folder / 'publication.json'
        if not receiptpath.exists(): return False
        receipt = read_json(receiptpath)
        require(type(receipt) is dict and set(receipt) == {'schema_version', 'set_id', 'pr_number',
            'commit', 'branch', 'report_path', 'report_sha256', 'pr_url'})
        require(type(receipt['schema_version']) is int and receipt['schema_version'] == 1)
        sid = status['set_id']; branch = 'research/' + folder.name + '_daily'
        require(receipt['set_id'] == sid and receipt['branch'] == branch)
        number = receipt['pr_number']; commit = receipt['commit']; rel = receipt['report_path']
        require(type(number) is int and number > 0)
        require(type(commit) is str and re.fullmatch('[a-f0-9]{40}', commit))
        require(type(rel) is str and not Path(rel).is_absolute() and '..' not in Path(rel).parts and
                str(Path(rel)) == rel and rel.startswith('research/' + sid + '/'))
        require(receipt['report_sha256'] == sha(raw))
        url = 'https://github.com/seanjeonn/sh-quant/pull/' + str(number)
        require(receipt['pr_url'] == url)
        worktree = self.worktree(folder.name)
        self.managed_repo(worktree); self.managed_repo(self.c['core_repo'])
        base = self.git(self.c['core_repo'], 'branch', '--show-current')
        require(base and base != branch)
        require(self.git(worktree, 'rev-parse', 'HEAD') == commit)
        require(self.git(worktree, 'ls-remote', '--exit-code', 'origin', 'refs/heads/' + branch).splitlines()
                == [commit + '\trefs/heads/' + branch])
        require(self.git_bytes(worktree, 'show', commit + ':' + rel) == raw)
        pr = self.github('pr', number)
        require(pr['url'] == url and pr['headRefName'] == branch and pr['headRefOid'] == commit)
        if pr['state'] == 'OPEN':
            require(pr['baseRefName'] == base)
        else:
            # Archived after integration (#41): the exact published head must already be contained in
            # remote main. Closed alone is not enough. Its original base is not compared with the
            # current checkout branch, which changes on a re-pin (#45).
            require(pr['state'] in ('CLOSED', 'MERGED'))
            require(self.github('compare', commit)['status'] in ('behind', 'identical'))
        files = pr['files']; require(type(files) is list and files)
        names = [entry['path'] for entry in files]
        require(len(names) == len(set(names)) and rel in names)
        for name in names:
            require(type(name) is str and '..' not in Path(name).parts and str(Path(name)) == name and
                    (name.startswith('research/' + sid + '/') or
                     re.fullmatch(r'strategies/' + re.escape(sid) + r'[a-z0-9_-]*\.toml', name) or
                     name == 'backlog.md'))
        return True

    def complete(self, folder, ledger, status):
        sid = status['set_id']
        require(re.fullmatch(re.escape(ledger['date']) + r'_[a-z0-9][a-z0-9_-]{0,63}', sid))
        require(status['state'] == 'completed' and status['conclusion'] in ('accept', 'defer', 'reject'))
        if not self.verify_publication(folder, status):
            if self.remaining(ledger) <= 0 or ledger['launches'] >= self.c['daily_max_launches']:
                return self.block(folder, ledger)
            ledger.update(status='publication_pending', set_id=sid)
            self.save_ledger(folder, ledger)
            return '연구 대기 ' + ledger['date']
        ledger.update(status='completed', set_id=sid, conclusion=status['conclusion'])
        self.save_ledger(folder, ledger)
        return '연구 완료 ' + sid + ' ' + status['conclusion']

    def research_prompt(self, folder, manifest, digest, worktree, ledger):
        evidence = {'date': ledger['date'], 'private_day': str(folder), 'manifest': str(manifest),
                    'manifest_sha256': digest, 'binary': self.c['binary'], 'binary_sha256': self.c['binary_sha256'],
                    'engine_commit': self.c['engine_commit'], 'registry': self.c['registry'],
                    'code_pins': self.c['code_pins'], 'worktree': str(worktree),
                    'supervisor_scope': str(folder / 'active-scope.json'),
                    'publication_command': [sys.executable, str(Path(__file__).resolve()),
                        '--config', self.config_path, '--mode', 'publication']}
        return '''Use sh-quant-automation. Sequential bounded research only in this day's worktree.
Read AGENTS.md, docs/research-runner.md, docs/daily-research-set.md, runner --help,
and hermes/templates/runner-plan.json first. Review prior lessons and backlog and current
approved issues/PRs before selecting a fresh executable hypothesis and bounded candidates.
Create/link a feature tracking issue BEFORE work. Do not rerun any legacy EMA day/set.
Use ONLY the supervisor's already frozen snapshot: NEVER acquire data or read credentials.
Create private_day/plan.json as a private schema2 plan with baseline and >=2 meaningful
variants. REQUIRED plan.supervisor_scope=private_day/active-scope.json (absolute stable
pointer path from evidence; preserve it unchanged across continuations).
machine_policy.selection MUST be mean_is_sharpe_v1 and machine_policy.evaluation
MUST be sharpe_excess_mdd_v1, with explicit exposed OOS. State a specific next
experiment with hypothesis and reason. No score-driven engine or policy changes.
Use research_set init, descriptor plan, commit/push exact public descriptor, checkpoint
plan, then bounded step. Freeze selection, descriptor selection, commit/push and exact
selection checkpoint, then step through evaluation/final report/lessons and Runner.verify.
No trial before plan checkpoint, no evaluation before selection checkpoint. Commit/push
only safe research artifacts on this working branch. Once runner completed, use the exact
publication_command below (--mode publication with the ACTUAL supplied --config path).
It renders deterministic public-safe JSON and persists private_day/publication-descriptor.json.
Copy EXACT bytes to research/SET_ID/publication.json; never invent a public summary.
Commit/push on research/DATE_daily, open/update PR on seanjeonn/sh-quant with base equal
to the pinned core_repo working branch. Read back remote head, exact report blob and PR.
Write private 0600 private_day/publication.json receipt with exactly schema_version=1,
set_id, pr_number (positive integer), commit (40 lowercase hex), branch,
report_path (repository-relative under research/SET_ID/), report_sha256 (exact bytes),
pr_url (https://github.com/seanjeonn/sh-quant/pull/NUMBER).
Only current-set research/ strategies/ and backlog.md may appear in the PR.
If runner is already completed, do NOT rerun trials: finish publication and receipt only.
Mark backlog completed ONLY after full completed verification. Preserve
all private evidence and failed attempts; raw model stdout is never proof of completion.
Do not modify src/, tools/, Cargo.*, config, engine, dashboard, old research/results or
another profile. No main merge/auto-merge, deployment/release, paid/live/account/order
API, account settings, credential reads, secret publication, destructive Git or forced push.
If blocked, preserve artifacts and record it; do not fabricate conclusions or retry forever.
Return at a checkpoint when budget is short. These prompt restrictions are not a sandbox.
Frozen private evidence (never publish paths or market values):
''' + encode(evidence).decode()

    def research(self, folder, ledger, snapshot, mode):
        manifest, digest = self.frozen_manifest(snapshot, ledger['date'])
        if 'expanded_data' in self.c: require(ledger.get('snapshot_sha256') == digest)
        if 'manifest_sha256' in ledger: require(ledger['manifest_sha256'] == digest)
        else: ledger['manifest_sha256'] = digest
        worktree = self.worktree(ledger['date'])
        require(self.remaining(ledger) > 0 and ledger['launches'] < self.c['daily_max_launches'])
        ledger.update(status='running', launches=ledger['launches'] + 1)
        self.save_ledger(folder, ledger)
        self.agent(folder, mode, self.research_prompt(folder, manifest, digest, worktree, ledger),
                   worktree, self.remaining(ledger))
        self.check_pins(worktree)
        _, current = self.frozen_manifest(snapshot, ledger['date'])
        require(current == digest)
        statuses = self.day_sets(ledger['date'])
        require(len(statuses) == 1)
        status = statuses[0]
        if status['state'] == 'completed': return self.complete(folder, ledger, status)
        require(status['state'] in ('await_plan_checkpoint', 'ready_trial', 'await_selection_checkpoint',
                                    'ready_evaluate', 'ready_finalize'))
        if self.remaining(ledger) <= 0 or ledger['launches'] >= self.c['daily_max_launches']:
            return self.block(folder, ledger)
        ledger.update(status='pending', set_id=status['set_id'])
        self.save_ledger(folder, ledger)
        return '연구 대기 ' + ledger['date']

    def reconcile_invocations(self, folder, ledger):
        counts = {'acquisition': 0, 'daily': 0, 'continue': 0}
        for inv in folder.glob('invocation-*'):
            private(inv, directory=True)
            start = read_json(inv / 'start.json'); end = read_json(inv / 'end.json')
            require(start['kind'] in counts and start['policy_sha256'] == self.policy_sha256)
            require(type(end['exit_code']) is int and end['exit_code'] == 0 and end['timed_out'] is False)
            require(ledger['started_epoch'] <= start['started_at'] <= end['ended_at'] <= self.day().timestamp())
            for stream in ('stdout', 'stderr'):
                require(sha(private(inv / (stream + '.log')).read_bytes()) == end[stream + '_sha256'])
            counts[start['kind']] += 1
        require(counts['acquisition'] == ledger['acquisition_attempts'] and
                counts['daily'] + counts['continue'] == ledger['launches'])

    def daily(self, mode):
        date = self.day().date().isoformat()
        folder = self.root / date
        ledgerpath = folder / 'ledger.json'
        if mode in ('continue', 'deadline') and not ledgerpath.exists(): return ''
        if ledgerpath.exists():
            ledger = self.read_ledger(folder)
            require(ledger['date'] == date and ledger['policy_sha256'] == self.policy_sha256)
            if ledger['status'] == 'blocked': return ''
            if ledger['status'] in ('completed', 'legacy_completed'):
                try:
                    if ledger['status'] == 'completed':
                        states = self.day_sets(date)
                        require(len(states) == 1 and states[0]['state'] == 'completed' and
                                states[0]['set_id'] == ledger['set_id'] and states[0]['conclusion'] == ledger['conclusion'])
                        require(self.verify_publication(folder, states[0]))
                    else:
                        item = next(i for i in self.c.get('legacy_completed', []) if i['date'] == date)
                        audit = self.auditor or self.core_module('research_contract').audit_legacy_ema
                        require(audit(item['public_dir'], item['private_dir'])['status'] == 'completed')
                    return ''
                except (Exception, KeyboardInterrupt): return self.block(folder, ledger)
            if ledger['status'] not in ('pending', 'publication_pending'): return self.block(folder, ledger)
        else:
            if self.day().strftime('%H:%M') < self.c['daily_start']: return ''
            # A pre-existing directory with no committed ledger is ambiguous.
            require(not folder.exists())
            mkdir(folder)
            ledger = {'schema_version': 1, 'date': date, 'started_epoch': self.day().timestamp(),
                      'policy_sha256': self.policy_sha256, 'status': 'initializing',
                      'launches': 0, 'acquisition_attempts': 0}
            self.save_ledger(folder, ledger)
        try:
            self.reconcile_invocations(folder, ledger)
            for item in self.c.get('legacy_completed', []):
                if item['date'] == date:
                    audit = self.auditor or self.core_module('research_contract').audit_legacy_ema
                    result = audit(item['public_dir'], item['private_dir'])
                    require(result['state'] == 'completed' if 'state' in result else result['status'] == 'completed')
                    ledger['status'] = 'legacy_completed'; self.save_ledger(folder, ledger)
                    return '기존 연구 확인 ' + date
            states = self.day_sets(date)
            if states and states[0]['state'] == 'completed':
                if self.verify_publication(folder, states[0]):
                    return self.complete(folder, ledger, states[0])
                ledger.update(status='publication_pending', set_id=states[0]['set_id'])
                self.save_ledger(folder, ledger)
            if self.remaining(ledger) <= 0 or ledger['launches'] >= self.c['daily_max_launches']:
                return self.block(folder, ledger)
            if mode == 'deadline': return ''
            snapshot = folder / 'snapshot'
            if not ledger['acquisition_attempts'] and not states:
                require(not snapshot.exists())
                if 'expanded_data' in self.c:
                    base, basehash = self.select_base(date)
                    ledger.update(base_manifest=str(base), base_manifest_sha256=basehash)
                ledger.update(status='acquiring', acquisition_attempts=1)
                self.save_ledger(folder, ledger)
                if 'expanded_data' in self.c:
                    expanded = self.c['expanded_data']
                    argv = [sys.executable, str(Path(self.c['core_repo']) / 'tools' / 'refresh_toss.py'),
                            '--universe-file', expanded['universe_file'], '--universe-sha256', expanded['universe_sha256'],
                            '--base-manifest', ledger['base_manifest'], '--base-sha256', ledger['base_manifest_sha256'],
                            '--env-file', self.c['env_file'], '--token-file', self.c['token_file'],
                            '--output', str(snapshot), '--start-date', expanded['start_date'],
                            '--cutoff-exclusive', date,
                            '--max-attempts', str(self.c['acquisition_max_attempts']),
                            '--max-minutes', str(self.c['acquisition_max_minutes']),
                            '--min-interval', str(self.c['min_interval'])]
                else:
                    argv = [sys.executable, str(Path(self.c['core_repo']) / 'tools' / 'prepare_toss.py'),
                            '--env-file', self.c['env_file'], '--token-file', self.c['token_file'],
                            '--output', str(snapshot), '--cutoff-exclusive', date,
                            '--max-attempts', str(self.c['acquisition_max_attempts']),
                            '--max-minutes', str(self.c['acquisition_max_minutes']),
                            '--min-interval', str(self.c['min_interval'])]
                self.launch(folder, 'acquisition', argv, self.c['core_repo'],
                            min(self.c['acquisition_max_minutes'] * 60, self.remaining(ledger)))
                if 'expanded_data' in self.c:
                    manifest, digest = self.frozen_manifest(snapshot, date)
                    value = read_json(manifest)
                    refresh = value.get('provenance', {}).get('refresh', {})
                    require(refresh.get('policy') == self.c['expanded_data']['refresh_policy'] and
                            refresh.get('base_manifest_sha256') == ledger['base_manifest_sha256'])
                    require(value['http_attempts'] <= self.c['acquisition_max_attempts'])
                    ledger['snapshot_sha256'] = digest
                    self.save_ledger(folder, ledger)
            # Validation and model continuation are performed only after acquisition
            # has a durable successful completion and frozen manifest.
            return self.research(folder, ledger, snapshot, mode)
        except (Exception, KeyboardInterrupt):
            return self.block(folder, ledger)

    def managed_repo(self, repo):
        require(self.git(repo, 'remote', 'get-url', 'origin') in (
            'https://github.com/seanjeonn/sh-quant.git', 'https://github.com/seanjeonn/sh-quant',
            'git@github.com:seanjeonn/sh-quant.git', 'git@github.com:seanjeonn/sh-quant'))
        return 'seanjeonn/sh-quant'

    def github(self, kind, number):
        reader = getattr(self, 'github_reader', None)
        if reader is not None:
            return reader(kind, number)
        if kind == 'compare':  # status of commit `number` relative to main: behind/identical = contained
            command = ['gh', 'api', 'repos/seanjeonn/sh-quant/compare/main...' + number, '--jq', '{status}']
        else:
            fields = ('number,url,body,state' if kind == 'issue' else
                      'url,state,baseRefName,headRefName,headRefOid,files')
            command = ['gh', kind, 'view', str(number), '--repo', 'seanjeonn/sh-quant', '--json', fields]
        result = subprocess.run(command, capture_output=True, timeout=30)
        require(result.returncode == 0)
        return decode(result.stdout)

    def weekly(self):
        year, week, _ = self.day().isocalendar()
        folder = self.root / ('week-%04d-W%02d' % (year, week))
        if folder.exists():
            private(folder, directory=True)
            # Never retry a failed or interrupted review automatically.
            require((folder / 'start.json').exists())
            read_json(folder / 'start.json')
            return ''
        mkdir(folder)
        start = self.day().timestamp()
        immutable(folder / 'start.json', encode({'schema_version': 1, 'started_epoch': start,
                   'policy_sha256': self.policy_sha256, 'attempts': 1}))
        try:
            repo = self.managed_repo(self.c['core_repo'])
            receiptpath = folder / 'weekly-review.json'
            prompt = '''Use sh-quant-automation. Weekly triage ONLY, no implementation.
Read AGENTS.md, docs/research-runner.md, prior research/lessons, approved issues,
issue comments and active PRs. Prioritize correctness/data/reproducibility blockers.
File or update managed bug reports/work proposals with templates, Source and Related Work;
never treat proposals as approved features. No code changes, engine changes, market APIs,
credential reads, other-profile edits, main merge/auto-merge, deployment/release, paid/live
or account operations. Verify exact issue read-back. Do not expose market metrics,
raw output, credentials or local private paths. Write a NEW private 0600 JSON receipt at
''' + str(receiptpath) + ''' with exactly these fields: schema_version=1,
completed=true, reviewed_at=timezone-aware ISO8601 time, managed_issue_urls=list of unique
https://github.com/''' + repo + '''/issues/NUMBER URLs actually reviewed and read back (maximum 50).
managed_issue_body_sha256=mapping of those exact URLs to SHA256 of actual UTF-8 issue bodies.
Do not claim created/updated work without specific independent change proof; this receipt proves review only.
An empty list is valid if there is nothing to file; do not fabricate work. stdout is not proof.
'''
            self.agent(folder, 'weekly', prompt, self.c['repo'])
            self.check_pins()
            receipt = read_json(receiptpath)
            require(type(receipt) is dict and set(receipt) == {'schema_version', 'completed', 'reviewed_at', 'managed_issue_urls', 'managed_issue_body_sha256'})
            require(type(receipt['schema_version']) is int and receipt['schema_version'] == 1 and receipt['completed'] is True)
            reviewed = dt.datetime.fromisoformat(receipt['reviewed_at'])
            require(reviewed.tzinfo is not None and start <= reviewed.timestamp() <= self.day().timestamp())
            urls = receipt['managed_issue_urls']
            require(type(urls) is list and all(type(u) is str and re.fullmatch(
                r'https://github\.com/' + re.escape(repo) + r'/issues/[1-9][0-9]*', u) for u in urls))
            require(len(set(urls)) == len(urls) and len(urls) <= 50)
            hashes = receipt['managed_issue_body_sha256']
            require(type(hashes) is dict and set(hashes) == set(urls))
            for url in urls:
                digest = hashes[url]
                require(type(digest) is str and re.fullmatch('[a-f0-9]{64}', digest))
                number = int(url.rsplit('/', 1)[1])
                actual = self.github('issue', number)
                require(type(actual['number']) is int and actual['number'] == number and actual['url'] == url)
                require(actual['state'] in ('OPEN', 'CLOSED') and type(actual['body']) is str)
                require(sha(actual['body'].encode()) == digest)
            immutable(folder / 'end.json', encode({'schema_version': 1, 'completed': True,
                'ended_epoch': self.day().timestamp(), 'receipt_sha256': sha(private(receiptpath).read_bytes()),
                'managed_count': len(urls)}))
            return '주간 검토 완료 ' + str(len(urls))
        except (Exception, KeyboardInterrupt):
            immutable(folder / 'end.json', encode({'schema_version': 1, 'completed': False,
                                                  'ended_epoch': self.day().timestamp()}))
            return '주간 검토 차단'

    def day_ledger_exists(self):
        folder = path(self.root / self.day().date().isoformat(), directory=True, missing=True)
        if not folder.exists(): return False
        private(folder, directory=True)
        return private(folder / 'ledger.json', missing=True).exists()

    def failed_start_path(self):
        root = private(self._policy_root, directory=True)
        folder = path(root / 'failed-starts', directory=True, missing=True)
        target = folder / (self.day().date().isoformat() + '.json')
        if folder.exists():
            private(folder, directory=True)
            private(target, missing=True)
        return target

    def record_failed_start(self, mode):
        # Manual-only recovery: no retry flag, no new ledger, no budget reset.
        # A constructor which has not validated the whole config may only emit
        # diagnostics to active HERMES_HOME, never a config-derived policy marker.
        if mode != 'daily' or not hasattr(self, '_trusted_root'): return
        now = self.day()
        if now.strftime('%H:%M') < self.c['daily_start']: return
        if (self.root / now.date().isoformat() / 'ledger.json').exists(): return
        target = self.failed_start_path()
        mkdir(target.parent)
        if target.exists():
            read_json(target)  # never overwrite even for a new policy
            return
        try:
            immutable(target, encode(dict(schema_version=1, date=now.date().isoformat(),
                started_epoch=getattr(self, '_attempt_epoch', now.timestamp()),
                policy_sha256=self.policy_sha256, recovery='manual_only')))
        except FileExistsError:
            read_json(target)  # concurrent first writer owns the immutable marker

    def run(self, mode):
        self._attempt_epoch = self.day().timestamp()
        self._diagnosed = False
        try:
            require(mode in MODES)
            self.stage = 'preflight'
            # Validate the evidence sink before doing any work. Failure is not
            # permission to continue without durable, profile-local evidence.
            self.diagnostic(mode, 'started', 'ok')
            self._diagnosed = False
            status = self._run(mode)
            if not self._diagnosed:
                blocked = type(status) is str and '차단' in status
                self.diagnostic(mode, 'blocked' if blocked else 'ok', self.stage if blocked else 'ok')
            return status
        except (Exception, KeyboardInterrupt):
            self.record_failed_start(mode)
            if not self._diagnosed:
                self.diagnostic(mode, 'blocked', self.stage)
            raise

    def _run(self, mode):
        if mode == 'publication':
            self.stage = 'publication'
            return self.publication()
        # Read-only preflight: an idle tick must never contend with daily start.
        # Repeat under the lock below; only daily may initialize a day.
        if mode == 'continue' and not self.day_ledger_exists():
            self.diagnostic(mode, 'quiet', 'idle_continue')
            return ''
        if mode == 'deadline' and not self.day_ledger_exists():
            late = self.day().hour >= 17
            self.diagnostic(mode, 'blocked' if late else 'quiet', 'missing_day_deadline')
            return '연구 차단 ' + self.day().date().isoformat() if late else ''
        self.stage = 'lock'
        lock = private(self.root / '.supervisor.lock', missing=True)
        self.lock_fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            until = time.monotonic() + (1.0 if mode == 'daily' else 0)
            while True:
                try:
                    fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = until - time.monotonic()
                    if mode == 'daily' and remaining > 0:
                        time.sleep(min(.05, remaining))
                        continue
                    self.diagnostic(mode, 'quiet' if mode == 'continue' else 'blocked', 'lock_busy')
                    if mode == 'continue': return ''
                    raise Blocked('blocked') from None
            self.stage = 'pin_validation'
            self.check_pins()
            if mode == 'canary':
                self.stage = 'canary'
                return self.canary()
            if mode == 'continue' and not self.day_ledger_exists():
                self.diagnostic(mode, 'quiet', 'idle_continue')
                return ''
            if mode == 'daily' and not self.day_ledger_exists() and self.failed_start_path().exists():
                read_json(self.failed_start_path())
                self.diagnostic(mode, 'blocked', 'preledger_failure_manual_only')
                return '연구 차단 ' + self.day().date().isoformat()
            self.activated()
            self.stage = 'weekly' if mode == 'weekly' else 'daily'
            if mode != 'weekly': return self.daily(mode)
            return self.weekly()
        finally:
            # Close, never LOCK_UN: surviving OwnedTrial retains this open file
            # description and excludes a new supervisor until its group is dead.
            os.close(self.lock_fd)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's ordinary diagnostic echoes arbitrary argv, including paths.
        raise Blocked('blocked')


def main(argv=None):
    supervisor = Supervisor.__new__(Supervisor)
    mode = 'unknown'
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument('--config', required=True, help='absolute private JSON configuration')
        parser.add_argument('--mode', required=True, choices=('canary', 'daily', 'continue', 'weekly', 'deadline', 'publication'))
        args = parser.parse_args(argv)
        mode = args.mode
        supervisor._attempt_epoch = time.time()
        supervisor.__init__(args.config)
        status = supervisor.run(mode)
        if args.mode == 'publication':
            require(type(status) is bytes)
            sys.stdout.buffer.write(status)
            return 0
        require(status == '' or re.fullmatch(
            r'(?:카나리 통과 [A-Za-z0-9_-]{8,100}|(?:연구 차단|연구 대기|기존 연구 확인) \d{4}-\d{2}-\d{2}|'
            r'연구 완료 \d{4}-\d{2}-\d{2}_[a-z0-9][a-z0-9_-]{0,63} (?:accept|defer|reject)|'
            r'주간 검토 완료 [0-9]+|주간 검토 차단)', status))
        if status: print(status)
        return 1 if '차단' in status else 0
    except (Exception, KeyboardInterrupt):
        try:
            supervisor.record_failed_start(mode)
            if not getattr(supervisor, '_diagnosed', False):
                supervisor.diagnostic(mode, 'blocked', getattr(supervisor, 'stage', 'arguments'))
        except (Exception, KeyboardInterrupt):
            pass  # fail closed; never fall back to config paths or raw errors
        print('자동화 차단')
        return 1


if __name__ == '__main__':
    sys.exit(main())
