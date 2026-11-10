#!/usr/bin/env python3
"""Issue #30: private, offline, incremental research lifecycle.

No acquisition, scheduling, shell execution, Git writes, or sealed holdout.
Every invocation performs at most one trial or lifecycle transition.
"""
import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import time
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')


class Blocked(ValueError):
    """Controlled, non-sensitive diagnostics only."""


def require(condition, code='invalid_evidence'):
    if not condition:
        raise Blocked(code)


def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(',', ':')) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(value, *, private=False, directory=False, missing=False):
    p = Path(value)
    require(p.is_absolute() and '..' not in p.parts, 'unsafe_path')
    for q in [p, *p.parents]:
        require(not q.is_symlink(), 'symlink_path')
        if private:
            require(not (q / '.git').exists(), 'private_path_in_git')
    if p.exists():
        s = p.stat()
        require(s.st_uid == os.getuid(), 'wrong_owner')
        require(stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode), 'wrong_file_type')
        if not directory:
            require(s.st_nlink == 1, 'hardlink_file')
        if private:
            require(stat.S_IMODE(s.st_mode) == (0o700 if directory else 0o600), 'unsafe_permissions')
    else:
        require(missing, 'missing_file')
    if private:
        s = p.parent.stat()
        require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o700, 'unsafe_parent')
    return p


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def immutable(path, raw):
    safe_path(path, private=True, missing=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    fsync_dir(path.parent)


def read(path):
    return safe_path(path, private=True).read_bytes()


def load(path):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'duplicate_json_key'); result[k] = v
        return result
    try:
        return json.loads(read(path), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Blocked('nonfinite_json')))
    except (ValueError, UnicodeError):
        raise Blocked('invalid_json') from None


def git(repo, *args):
    env = {'PATH': os.defpath, 'HOME': str(Path.home()), 'GIT_TERMINAL_PROMPT': '0',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
    p = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=30, env=env)
    require(p.returncode == 0, 'git_read_failed')
    return p.stdout


@contextmanager
def registry_lock(registry, create=False):
    registry = safe_path(registry, private=True, directory=True, missing=create)
    if not registry.exists():
        registry.mkdir(mode=0o700); fsync_dir(registry.parent)
    lock = registry / '.lock'
    safe_path(lock, private=True, missing=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked('worker_busy') from None
        yield fd
    finally:
        # Do NOT LOCK_UN: a surviving child's inherited fd must retain this lock.
        os.close(fd)


def contract():
    try:
        import research_contract
    except ImportError:
        from tools import research_contract
    return research_contract


ROOT_BUILD_INPUTS = ('Cargo.toml', 'Cargo.lock', 'build.rs', 'rust-toolchain', 'rust-toolchain.toml')


def code_tree(repo):
    names = git(repo, 'ls-files', '-z', '--', 'src', *ROOT_BUILD_INPUTS,
                '.cargo', 'tools').decode().split('\0')
    result = {}
    for name in sorted(n for n in names if n):
        p = safe_path(repo / name)
        result[name] = digest(p.read_bytes())
    require('Cargo.lock' in result and any(n.startswith('src/') for n in result), 'missing_code')
    # The map's keys freeze presence as well as content, including untracked roots.
    for name in ROOT_BUILD_INPUTS:
        p = repo / name
        if p.exists() or p.is_symlink():
            result[name] = digest(safe_path(p).read_bytes())
    # Include untracked Rust/config files: compilation cannot silently gain an input.
    for folder in ('src', '.cargo', 'tools'):
        if (repo / folder).exists():
            for p in sorted((repo / folder).rglob('*')):
                if '__pycache__' in p.parts or p.suffix == '.pyc': continue
                if p.is_file() or p.is_symlink():
                    result[str(p.relative_to(repo))] = digest(safe_path(p).read_bytes())
    return result


def input_fingerprint(planpath, repo, binary, manifest):
    raw = read(planpath); plan = load(planpath)
    try:
        contract().validate_plan(plan)
    except contract().ContractError:
        raise Blocked('invalid_contract') from None
    for candidate in [plan['baseline'], *plan['variants']]:
        signal_text = candidate['signal']
        require(isinstance(signal_text, str) and len(signal_text) <= 16384
                and signal_text.isascii() and not re.search(r'\bref\s*\(', signal_text), 'external_signal_forbidden')
        parameters = candidate['parameters']
        require(isinstance(parameters, dict) and len(parameters) <= 32, 'invalid_parameters')
        require(all(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', k) and type(v) in (int, float, str, bool)
                    and (type(v) is not float or math.isfinite(v))
                    and (type(v) is not str or len(v) <= 256) for k, v in parameters.items()), 'invalid_parameters')
    repo = safe_path(repo, directory=True)
    binary = safe_path(binary)
    require(os.access(binary, os.X_OK) and binary.stat().st_mode & 0o022 == 0, 'unsafe_binary')
    magic = binary.read_bytes()[:4]
    require(magic in (b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'), 'native_binary_required')
    require(digest(binary.read_bytes()) == plan['binary_sha256'], 'binary_changed')
    require(digest((repo / 'Cargo.lock').read_bytes()) == plan['cargo_lock_sha256'], 'lock_changed')
    require(digest(read(manifest)) == plan['data_manifest_sha256'], 'manifest_changed')
    require(git(repo, 'cat-file', '-t', plan['engine_commit']).strip() == b'commit', 'missing_engine_commit')
    # Engine inputs must equal the pinned revision, not merely HEAD metadata.
    for name in ('src', *ROOT_BUILD_INPUTS, '.cargo'):
        require(not git(repo, 'diff', '--no-ext-diff', '--no-textconv', plan['engine_commit'], '--', name), 'dirty_engine')
    data = load(manifest)
    require(data.get('status') == 'complete' and isinstance(data.get('entries'), list) and data['entries'], 'incomplete_manifest')
    snapshots = {}
    for entry in data['entries']:
        name = entry['path']; rel = Path(name)
        require(not rel.is_absolute() and '..' not in rel.parts, 'unsafe_snapshot_path')
        p = Path(manifest).parent / rel
        require(digest(read(p)) == entry['sha256'], 'snapshot_changed')
        require(name not in snapshots, 'duplicate_snapshot')
        snapshots[name] = entry['sha256']
    return plan, {'plan_sha256': digest(raw), 'repo': str(repo), 'binary': str(binary),
                  'manifest': str(manifest), 'plan_source': str(planpath),
                  'code_tree': code_tree(repo), 'snapshots': snapshots,
                  'binary_sha256': plan['binary_sha256'], 'manifest_sha256': plan['data_manifest_sha256']}


def initialize(registry, planpath, repo, binary, manifest):
    registry, planpath, repo, binary, manifest = map(Path, (registry, planpath, repo, binary, manifest))
    plan, config = input_fingerprint(planpath, repo, binary, manifest)
    sid = plan['set_id']
    require(re.fullmatch(r'\d{4}-\d{2}-\d{2}_[a-z0-9][a-z0-9_-]{0,63}', sid), 'invalid_set_id')
    day = dt.date.fromisoformat(sid[:10]); today = dt.datetime.now(KST).date()
    require(day <= today, 'future_set')
    with registry_lock(registry, create=True):
        folder = registry / sid
        for p in registry.iterdir():
            if p.name.startswith(sid[:10] + '_'):
                require(p.name == sid, 'day_already_registered')
        if folder.exists():
            safe_path(folder, private=True, directory=True)
            require(read(folder / 'plan.json') == read(planpath) and load(folder / 'config.json') == config,
                    'immutable_init_mismatch')
        else:
            require(day == today or plan.get('operator_canary') is True, 'past_set_requires_canary')
            folder.mkdir(mode=0o700); fsync_dir(registry)
            immutable(folder / 'plan.json', read(planpath))
            immutable(folder / 'manifest.json', read(manifest))
            immutable(folder / 'config.json', encode(config))
            immutable(folder / 'binary.snapshot', binary.read_bytes())
            immutable(folder / 'code.snapshot.json', encode({name: (repo / name).read_bytes().hex() for name in config['code_tree']}))
            immutable(folder / 'events.jsonl', b'')
            Runner.append_raw(folder, {'event': 'init', 'config_sha256': digest(encode(config)),
                                      'plan_sha256': config['plan_sha256'], 'time': time.time()})
    with Runner(registry, sid) as runner:
        return runner.verify()


class Runner:
    def __init__(self, registry, set_id, *, launch=subprocess.Popen):
        require(re.fullmatch(r'\d{4}-\d{2}-\d{2}_[a-z0-9][a-z0-9_-]{0,63}', set_id), 'invalid_set_id')
        self.registry = Path(registry); self.folder = self.registry / set_id
        self.set_id = set_id; self.launch = launch

    def __enter__(self):
        self.lock = registry_lock(self.registry); self.fd = self.lock.__enter__()
        try:
            safe_path(self.folder, private=True, directory=True)
            self.plan = load(self.folder / 'plan.json'); self.config = load(self.folder / 'config.json')
            self.events = self.read_events()
            require(self.events and self.events[0]['event'] == 'init', 'missing_init')
            require(self.events[0]['config_sha256'] == digest(encode(self.config)), 'config_changed')
            require(self.events[0]['plan_sha256'] == digest(read(self.folder / 'plan.json')), 'plan_changed')
            self.verify_inputs()
            return self
        except BaseException:
            self.lock.__exit__(None, None, None); raise

    def __exit__(self, *args):
        return self.lock.__exit__(*args)

    @staticmethod
    def append_raw(folder, event):
        path = folder / 'events.jsonl'; previous = read(path)
        event = dict(event, previous=digest(previous))
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        with os.fdopen(fd, 'ab') as f:
            f.write(encode(event)); f.flush(); os.fsync(f.fileno())

    def log_hashes(self, trial):
        return {name: digest(read(trial / name)) if (trial / name).exists() else None
                for name in ('stdout.log', 'stderr.log')}

    def append(self, event):
        if event['event'] == 'end':
            start = next(e for e in self.events if e['event'] == 'start' and e['run_id'] == event['run_id'])
            trial, _ = self.trial_paths(start)
            event = dict(event, log_sha256=self.log_hashes(trial))
        self.append_raw(self.folder, dict(event, time=time.time()))
        self.events = self.read_events()

    def read_events(self):
        raw = read(self.folder / 'events.jsonl'); previous = b''; events = []
        for line in raw.splitlines(keepends=True):
            require(line.endswith(b'\n'), 'partial_journal')
            value = json.loads(line)
            require(value['previous'] == digest(previous), 'corrupt_journal')
            events.append(value); previous += line
        return events

    def verify_inputs(self):
        c = self.config
        _, current = input_fingerprint(Path(c['plan_source']), Path(c['repo']), Path(c['binary']), Path(c['manifest']))
        require(current == c, 'provenance_changed')
        require(read(self.folder / 'plan.json') == read(Path(c['plan_source'])), 'plan_changed')
        require(read(self.folder / 'manifest.json') == read(Path(c['manifest'])), 'manifest_changed')
        require(digest(read(self.folder / 'binary.snapshot')) == c['binary_sha256'], 'binary_snapshot_changed')
        snapshot = load(self.folder / 'code.snapshot.json')
        require({name: digest(bytes.fromhex(value)) for name, value in snapshot.items()} == c['code_tree'], 'code_snapshot_changed')

    def has(self, event, **fields):
        return any(e['event'] == event and all(e.get(k) == v for k, v in fields.items()) for e in self.events)

    def descriptor_bytes(self, kind):
        return encode({'schema_version': 2, 'set_id': self.set_id, 'kind': kind,
                       'private_sha256': digest(read(self.folder / (kind + '.json'))),
                       'holdout_status': 'exposed'})

    def descriptor(self, kind):
        require(kind in ('plan', 'selection'), 'invalid_descriptor_kind')
        source = self.folder / (kind + '.json')
        if kind == 'selection':
            require(self.has('selection'), 'selection_not_frozen')
        raw = self.descriptor_bytes(kind)
        destination = self.folder / (kind + '.public.json')
        if destination.exists():
            require(read(destination) == raw, 'descriptor_changed')
        else:
            require(not self.has('start') if kind == 'plan' else not self.has('evaluation'),
                    'late_descriptor_forbidden')
            immutable(destination, raw)
        return raw

    def check_git_checkpoint(self, evidence):
        repo = Path(self.config['repo']); kind = evidence['kind']; commit = evidence['commit']
        require(re.fullmatch(r'[0-9a-f]{40}', commit), 'invalid_commit')
        require(evidence['remote'] == 'origin', 'remote_not_allowed')
        branch = evidence['branch']
        require(re.fullmatch(r'(?:research|feat|fix)/[A-Za-z0-9][A-Za-z0-9_/-]{0,120}', branch)
                and '..' not in branch and '//' not in branch and not branch.endswith('/'), 'unsafe_branch')
        rel = evidence['path']; p = Path(rel)
        require(not p.is_absolute() and '..' not in p.parts and re.fullmatch(r'[A-Za-z0-9_./-]+', rel), 'unsafe_git_path')
        require(git(repo, 'cat-file', '-t', commit).strip() == b'commit', 'not_commit')
        expected = read(self.folder / (kind + '.public.json'))
        blob = git(repo, 'show', commit + ':' + rel)
        require(blob == expected and digest(blob) == evidence['descriptor_sha256'], 'checkpoint_blob_mismatch')
        remote = git(repo, 'ls-remote', '--exit-code', 'origin', 'refs/heads/' + branch).decode().splitlines()
        require(len(remote) == 1, 'missing_remote_branch')
        head, ref = remote[0].split('\t')
        require(ref == 'refs/heads/' + branch and re.fullmatch(r'[0-9a-f]{40}', head), 'invalid_remote_head')
        # No fetch: the remotely observed head must already be known locally.
        git(repo, 'merge-base', '--is-ancestor', commit, head)
        git(repo, 'merge-base', '--is-ancestor', self.plan['engine_commit'], commit)
        if kind == 'selection':
            plan_checkpoint = next(e for e in self.events if e['event'] == 'checkpoint' and e['kind'] == 'plan')
            require(commit != plan_checkpoint['commit'], 'selection_requires_later_commit')
            git(repo, 'merge-base', '--is-ancestor', plan_checkpoint['commit'], commit)

    def checkpoint(self, kind, commit, remote, branch, path):
        require(kind in ('plan', 'selection'), 'invalid_checkpoint_kind')
        require(not self.has('checkpoint', kind=kind), 'checkpoint_already_frozen')
        require(not self.has('start') if kind == 'plan' else self.has('selection') and not self.has('evaluation'), 'checkpoint_wrong_stage')
        descriptor = self.descriptor(kind)
        evidence = {'event': 'checkpoint', 'kind': kind, 'commit': commit, 'remote': remote,
                    'branch': branch, 'path': path, 'descriptor_sha256': digest(descriptor)}
        self.check_git_checkpoint(evidence)
        self.append(evidence)
        return self.status()

    def candidates(self):
        return [self.plan['baseline'], *self.plan['variants']]

    def starts(self):
        return [e for e in self.events if e['event'] == 'start']

    def ends(self):
        return {e['run_id']: e for e in self.events if e['event'] == 'end'}

    def trial_paths(self, start):
        rid = start['run_id']
        require(re.fullmatch(re.escape(self.set_id) + r'__[A-Za-z0-9_-]+', rid), 'unsafe_run_id')
        require(start['result_dir'] == 'trials/' + rid + '/results', 'unsafe_trial_path')
        return self.folder / 'trials' / rid, self.folder / start['result_dir']

    def result(self, start):
        trial, output = self.trial_paths(start)
        safe_path(trial, private=True, directory=True)
        safe_path(output, private=True, directory=True)
        rows = load(output / 'index.json'); rid = start['run_id']
        require(isinstance(rows, list) and len(rows) == 1 and rows[0].get('id') == rid
                and rows[0].get('status') == 'ok', 'invalid_result_index')
        row = rows[0]
        require(set(row.get('markets', {})) == {'US', 'KR'}, 'missing_market')
        for market in row['markets'].values():
            for split in ('is', 'oos'):
                metrics = market.get(split)
                require(isinstance(metrics, dict), 'missing_metrics')
                for key in ('sharpe', 'cagr', 'mdd', 'excess_cagr'):
                    value = metrics.get(key)
                    require(type(value) in (int, float) and math.isfinite(value), 'invalid_metric')
        detail = load(output / (rid + '.json'))
        require(detail.get('id') == rid and set(detail.get('curves', {})) == {'US', 'KR'}, 'invalid_detail')
        proof = {'index_sha256': digest(read(output / 'index.json')),
                 'detail_sha256': digest(read(output / (rid + '.json'))), 'entry_sha256': digest(encode(row))}
        return row, proof

    def successes(self):
        rows = []; ends = self.ends(); seen = set()
        for start in self.starts():
            end = ends.get(start['run_id'])
            if end and end['status'] == 'ok':
                require(start['candidate_id'] not in seen, 'successful_rerun')
                row, proof = self.result(start)
                require(all(end.get(k) == v for k, v in proof.items()), 'result_changed')
                row = dict(row, id=start['candidate_id'])
                rows.append(row); seen.add(start['candidate_id'])
        return rows

    def selection_value(self):
        rows = self.successes()
        require(len(rows) == len(self.candidates()), 'incomplete_candidates')
        selected = contract().select_candidate(self.plan, rows)
        return dict(selected, plan_sha256=self.config['plan_sha256'],
                    entries_sha256=digest(encode(rows)),
                    attempts_sha256=digest(encode([e for e in self.events if e['event'] in ('start', 'child', 'end')])),
                    holdout_status='exposed')

    def evaluation_value(self):
        selected = self.selection_value()
        require(load(self.folder / 'selection.json') == selected, 'selection_changed')
        return contract().evaluate_candidate(self.plan, self.successes(), selected['selected_run_id'])

    def verify(self):
        self.verify_inputs()
        allowed = {'init', 'checkpoint', 'start', 'child', 'end', 'selection', 'evaluation', 'complete', 'blocked'}
        seen_starts = {}; ended = set(); plan_gate = False; selection_gate = False
        selected = False; evaluated = False; complete = False
        for e in self.events:
            kind = e['event']; require(kind in allowed and not complete, 'invalid_event_order')
            if kind == 'checkpoint':
                require(e['kind'] in ('plan', 'selection'), 'invalid_checkpoint')
                require((not seen_starts and not plan_gate) if e['kind'] == 'plan' else selected and not evaluated and not selection_gate, 'checkpoint_order')
                # The owner can recompute this journal's hash chain. It is not a
                # publication receipt: independently re-read origin on every verify.
                # Unavailable remotes block readiness; there is no offline bypass.
                raw = read(self.folder / (e['kind'] + '.public.json'))
                require(raw == self.descriptor_bytes(e['kind']) and digest(raw) == e['descriptor_sha256'], 'descriptor_changed')
                self.check_git_checkpoint(e)
                if e['kind'] == 'plan': plan_gate = True
                else: selection_gate = True
            elif kind == 'start':
                require(plan_gate and not selected and len(seen_starts) == len(ended), 'start_order')
                rid = e['run_id']; require(rid not in seen_starts, 'duplicate_attempt')
                candidate = next((c for c in self.candidates() if c['run_id'] == e['candidate_id']), None)
                require(candidate is not None and e['parameters'] == candidate['parameters'] and e['signal'] == candidate['signal'], 'candidate_changed')
                expected = candidate['run_id'] if e['repair'] == 0 else candidate['run_id'] + '__repair' + str(e['repair'])
                require(rid == expected and type(e['repair']) is int and 0 <= e['repair'] <= self.plan['budget']['max_repairs'], 'invalid_repair')
                trial, output = self.trial_paths(e)
                strategy = trial / (rid + '.toml'); raw_strategy = read(strategy)
                require(digest(raw_strategy) == e['strategy_sha256'] and raw_strategy == self.strategy_bytes(candidate, rid), 'strategy_changed')
                require(e['command'] == self.trial_command(strategy, output), 'command_changed')
                require(e['engine_commit'] == self.plan['engine_commit'] and e['data_manifest_sha256'] == self.plan['data_manifest_sha256'], 'attempt_provenance')
                seen_starts[rid] = e
            elif kind == 'child':
                require(e['run_id'] in seen_starts and e['run_id'] not in ended, 'child_order')
            elif kind == 'end':
                require(e['run_id'] in seen_starts and e['run_id'] not in ended and e['status'] in ('ok', 'failed', 'interrupted'), 'end_order')
                require(e['time'] >= seen_starts[e['run_id']]['time'], 'time_reversed')
                trial, _ = self.trial_paths(seen_starts[e['run_id']])
                require(e.get('log_sha256') == self.log_hashes(trial), 'log_changed')
                ended.add(e['run_id'])
            elif kind == 'selection':
                require(plan_gate and not selected and len(ended) == len(seen_starts), 'selection_order')
                require(load(self.folder / 'selection.json') == self.selection_value(), 'selection_changed')
                require(digest(read(self.folder / 'selection.json')) == e['sha256'], 'selection_digest')
                selected = True
            elif kind == 'evaluation':
                require(selection_gate and not evaluated, 'evaluation_order')
                require(load(self.folder / 'evaluation.json') == self.evaluation_value(), 'evaluation_changed')
                require(digest(read(self.folder / 'evaluation.json')) == e['sha256'], 'evaluation_digest')
                evaluated = True
            elif kind == 'complete':
                require(evaluated and not self.has('blocked') and len(self.successes()) == len(self.candidates()), 'false_completion')
                require(0 <= e['time'] - self.starts()[0]['time'] <= self.plan['budget']['max_wall_minutes'] * 60, 'completion_wall_budget')
                require(load(self.folder / 'evaluation.json')['conclusion'] == e['conclusion'], 'false_conclusion')
                for name in ('report', 'lessons'):
                    require(digest(read(self.folder / (name + '.json'))) == e[name + '_sha256'], 'missing_report_or_lessons')
                require(load(self.folder / 'report.json') == self.report_value(), 'report_changed')
                require(load(self.folder / 'lessons.json') == self.lessons_value(), 'lessons_changed')
                complete = True
        require(len(seen_starts) <= self.plan['budget']['max_attempts'], 'attempt_budget')
        require(sum(e['repair'] > 0 for e in seen_starts.values()) <= self.plan['budget']['max_repairs'], 'repair_budget')
        self.successes()
        return self.status(verified=True)

    def status(self, verified=False):
        if not verified:
            return self.verify()
        state = 'ready_trial' if self.has('checkpoint', kind='plan') else 'await_plan_checkpoint'
        if self.has('selection'): state = 'await_selection_checkpoint'
        if self.has('checkpoint', kind='selection'): state = 'ready_evaluate'
        if self.has('evaluation'): state = 'ready_finalize'
        if self.has('blocked'): state = 'blocked'
        result = {'state': state, 'set_id': self.set_id, 'attempt_count': len(self.starts())}
        if self.has('complete'):
            result.update(state='completed', conclusion=load(self.folder / 'evaluation.json')['conclusion'])
        return result

    def remaining(self):
        starts = self.starts()
        if not starts: return self.plan['budget']['max_wall_minutes'] * 60
        elapsed = time.time() - starts[0]['time']
        require(elapsed >= 0, 'clock_reversed')
        return self.plan['budget']['max_wall_minutes'] * 60 - elapsed

    def save_phase(self, name, value):
        raw = encode(value); path = self.folder / (name + '.json')
        if path.exists(): require(read(path) == raw, 'immutable_phase_changed')
        else: immutable(path, raw)
        self.append({'event': name, 'sha256': digest(raw)})

    def report_value(self):
        return {'schema_version': 2, 'set_id': self.set_id, 'holdout_status': 'exposed',
                'plan_sha256': self.config['plan_sha256'], 'entries': self.successes(),
                'selection': self.selection_value(), 'evaluation': self.evaluation_value(),
                'attempts': [e for e in self.events if e['event'] in ('start', 'child', 'end')],
                'limitations': ['OOS exposed; not independent validation', 'No acquisition or scheduling',
                                'Parameter sensitivity is the preregistered finite comparison only'],
                'tracking_issue': self.plan['tracking_issue'],
                'next_experiment': self.plan['next_experiment']}

    def lessons_value(self):
        selection = self.selection_value(); evaluation = self.evaluation_value()
        ranking = {item['run_id']: item for item in selection['ranking']}
        attempts = {start['candidate_id']: start['run_id'] for start in self.starts()
                    if self.ends().get(start['run_id'], {}).get('status') == 'ok'}
        candidates = []
        for row in self.successes():
            rid = row['id']; observations = {}
            for market, metrics in row['markets'].items():
                is_sharpe = metrics['is']['sharpe']; oos_sharpe = metrics['oos']['sharpe']
                observations[market] = {
                    'sharpe_vs_is': 'lower' if oos_sharpe < is_sharpe else 'higher' if oos_sharpe > is_sharpe else 'equal',
                    'sharpe_positive': oos_sharpe > 0,
                    'excess_cagr_nonnegative': metrics['oos']['excess_cagr'] >= 0}
            candidates.append({'candidate_id': rid, 'run_id': attempts[rid],
                'selected': rid == selection['selected_run_id'],
                'metrics_is': {m: v['is'] for m, v in row['markets'].items()},
                'is_means': {k: v for k, v in ranking[rid].items() if k != 'run_id'},
                'metrics_oos': {m: v['oos'] for m, v in row['markets'].items()},
                'oos_observations': observations})
        return {'set_id': self.set_id, 'holdout_status': 'exposed',
                'conclusion': evaluation['conclusion'], 'candidates': candidates,
                'evaluation': evaluation,
                'lesson': 'Selection used preregistered IS means only. These private OOS observations are exposed, not independent validation.',
                'next_experiment': self.plan['next_experiment'],
                'tracking_issue': self.plan['tracking_issue']}

    def recover(self):
        pending = [e for e in self.starts() if e['run_id'] not in self.ends()]
        if not pending: return False
        require(len(pending) == 1, 'multiple_pending_attempts')
        start = pending[0]; _, output = self.trial_paths(start)
        # The inherited registry flock excludes any surviving direct engine process.
        # A result is committed only when both index and detail validate, never by exit status alone.
        if (output / 'index.json').exists():
            _, proof = self.result(start)
            self.append(dict(proof, event='end', run_id=start['run_id'], status='ok', exit_code=None, recovered=True))
        elif output.exists() and any(output.iterdir()):
            raise Blocked('ambiguous_partial_result')
        else:
            self.append({'event': 'end', 'run_id': start['run_id'], 'status': 'interrupted', 'exit_code': None, 'recovered': True})
        return True

    def strategy_bytes(self, candidate, rid):
        # JSON basic strings (ASCII signal) are valid TOML basic strings.
        text = '\n'.join(k + ' = ' + json.dumps(v, ensure_ascii=True) for k, v in
                         [('name', rid), ('hypothesis', self.plan['hypothesis']), ('signal', candidate['signal'])])
        text += '\ntags = [' + json.dumps('set:' + self.set_id) + ']\nparents = []\nsource = "agent"\n'
        return text.encode()

    def trial_command(self, strategy, output):
        return [self.config['binary'], 'run', str(strategy), '--data-manifest', self.config['manifest'], '--output-dir', str(output)]

    def run_trial(self):
        rows = self.successes(); done = {r['id'] for r in rows}
        candidate = next(c for c in self.candidates() if c['run_id'] not in done)
        previous = [s for s in self.starts() if s['candidate_id'] == candidate['run_id']]
        repairs = len(previous)
        require(len(self.starts()) < self.plan['budget']['max_attempts'], 'attempt_budget')
        require(sum(s['repair'] > 0 for s in self.starts()) + bool(repairs) <= self.plan['budget']['max_repairs'], 'repair_budget')
        remaining = self.remaining(); require(remaining > 0, 'wall_budget')
        rid = candidate['run_id'] + ('__repair' + str(repairs) if repairs else '')
        trials = self.folder / 'trials'
        if not trials.exists(): trials.mkdir(mode=0o700); fsync_dir(self.folder)
        trial = trials / rid; require(not trial.exists(), 'unrecorded_trial_artifacts')
        trial.mkdir(mode=0o700); fsync_dir(trials)
        output = trial / 'results'; output.mkdir(mode=0o700)
        strategy = trial / (rid + '.toml'); immutable(strategy, self.strategy_bytes(candidate, rid))
        command = self.trial_command(strategy, output)
        start = {'event': 'start', 'run_id': rid, 'candidate_id': candidate['run_id'], 'repair': repairs,
                 'role': 'repair' if repairs else 'baseline' if candidate == self.plan['baseline'] else 'variant',
                 'parameters': candidate['parameters'], 'signal': candidate['signal'],
                 'strategy_sha256': digest(read(strategy)), 'command': command,
                 'engine_commit': self.plan['engine_commit'], 'data_manifest_sha256': self.plan['data_manifest_sha256'],
                 'result_dir': str(output.relative_to(self.folder)), 'host': socket.gethostname(),
                 'worker_pid': os.getpid(), 'binary_sha256': self.plan['binary_sha256']}
        self.append(start)  # Durable attempt charge BEFORE creating the child.
        child = None; rc = None; timed_out = False
        env = {'PATH': os.defpath, 'TZ': 'Asia/Seoul', 'HOME': str(Path.home())}
        with os.fdopen(os.open(trial / 'stdout.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stdout, \
             os.fdopen(os.open(trial / 'stderr.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stderr:
            try:
                child = OwnedTrial(self.launch, command, timeout=min(TRIAL_TIMEOUT, remaining),
                                   cwd=self.config['repo'], env=env, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, pass_fds=(self.fd,))
                self.append({'event': 'child', 'run_id': rid, 'pid': child.pid,
                             'host': socket.gethostname(), 'executable_sha256': self.plan['binary_sha256']})
                rc = child.wait()
                timed_out = child.timed_out
            except BaseException:
                if child is not None: terminate_child(child)
                raise
            finally:
                stdout.flush(); stderr.flush(); os.fsync(stdout.fileno()); os.fsync(stderr.fileno())
        self.verify_inputs()
        if (output / 'index.json').exists():
            _, proof = self.result(self.starts()[-1])
            self.append(dict(proof, event='end', run_id=rid, status='ok', exit_code=rc, timeout=timed_out))
        else:
            self.append({'event': 'end', 'run_id': rid, 'status': 'failed', 'exit_code': rc, 'timeout': timed_out})

    def step(self):
        state = self.verify()['state']
        if state in ('await_plan_checkpoint', 'await_selection_checkpoint', 'completed', 'blocked'):
            return self.status()
        try:
            if self.recover(): return self.status()
            require(self.remaining() > 0, 'wall_budget')
            if state == 'ready_trial':
                if len(self.successes()) < len(self.candidates()): self.run_trial()
                else: self.save_phase('selection', self.selection_value())
            elif state == 'ready_evaluate':
                self.save_phase('evaluation', self.evaluation_value())
            elif state == 'ready_finalize':
                for name, value in [('report', self.report_value()), ('lessons', self.lessons_value())]:
                    path = self.folder / (name + '.json'); raw = encode(value)
                    if path.exists(): require(read(path) == raw, 'final_artifact_changed')
                    else: immutable(path, raw)
                self.append({'event': 'complete', 'conclusion': self.evaluation_value()['conclusion'],
                             'report_sha256': digest(read(self.folder / 'report.json')),
                             'lessons_sha256': digest(read(self.folder / 'lessons.json'))})
        except Blocked:
            self.append({'event': 'blocked', 'reason': 'evidence_or_budget_blocker'})
            raise
        return self.status()


TRIAL_TIMEOUT = 300


class OwnedTrial:
    """A live session leader cleans its OWN group, even after worker SIGKILL.

    macOS Python lacks waitid(WNOWAIT). A forked, fixed supervisor instead
    retains group ownership until cleanup; the parent never signals a saved PID.
    Only the Python test API can inject launch. The CLI still launches the pinned
    native binary, with no command/helper option exposed to users.
    """
    def __init__(self, launch, command, *, timeout, **kwargs):
        self.report, report_write = os.pipe()
        control_read, self.control = os.pipe()
        self.returncode = None; self.timed_out = False; self.reaped = False
        try:
            self.pid = os.fork()
        except BaseException:
            for fd in (self.report, report_write, control_read, self.control): os.close(fd)
            raise
        if self.pid == 0:
            os.close(self.report); os.close(self.control)
            self.supervise(launch, command, timeout, kwargs, report_write, control_read)
            os._exit(125)
        os.close(report_write); os.close(control_read)

    @staticmethod
    def supervise(launch, command, timeout, kwargs, report, control):
        import select
        # No group signal is used unless setsid succeeded in this very process.
        try: os.setsid()
        except BaseException: os._exit(125)
        value = {'error': True}
        try:
            deadline = time.monotonic() + timeout
            child = launch(command, start_new_session=False, **kwargs)
            # Caught handlers reset to default on exec; the engine does not
            # inherit SIG_IGN. Only the supervisor ignores group TERM cleanup.
            signal.signal(signal.SIGTERM, lambda *_: None)
            cancel = False; timed_out = False
            while child.poll() is None:
                timed_out = time.monotonic() >= deadline
                if timed_out or cancel: break
                if control is not None and select.select([control], [], [], .02)[0]:
                    message = os.read(control, 1)
                    if message: cancel = True
                    else:
                        # A killed parent is not a cancellation: finish the owned
                        # engine, still bounded by the original absolute deadline.
                        os.close(control); control = None
                elif control is None: time.sleep(.02)
            if child.returncode is None:
                os.killpg(os.getpgrp(), signal.SIGTERM)
                time.sleep(.2)
                rc = child.poll()
                if rc is None: rc = -signal.SIGKILL
            else: rc = child.returncode
            value = {'exit_code': rc, 'timeout': timed_out}
        except BaseException:
            pass
        finally:
            try: os.write(report, encode(value))
            except OSError: pass  # parent may already be dead
            # This PID is still alive and is its own group leader. There is no
            # poll/reap/PID-recycling gap, including on normal native exit.
            os.killpg(os.getpgrp(), signal.SIGKILL)
            os._exit(125)

    def wait(self):
        if not self.reaped:
            os.waitpid(self.pid, 0)
            self.reaped = True
            try:
                raw = os.read(self.report, 4096)
                value = json.loads(raw)
                require(not value.get('error'), 'engine_launch_failed')
                self.returncode = value['exit_code']; self.timed_out = value['timeout']
            finally:
                os.close(self.report); os.close(self.control)
        return self.returncode

    def stop(self):
        if not self.reaped:
            try: os.write(self.control, b's')
            except BrokenPipeError: pass
            self.wait()


def terminate_child(child):
    child.stop()



def parser():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    for name in ('init', 'descriptor', 'checkpoint', 'step', 'verify', 'status'):
        sub = commands.add_parser(name)
        sub.add_argument('--registry', required=True, help='absolute private directory outside Git')
        if name == 'init':
            for flag in ('plan', 'repo', 'binary', 'manifest'):
                sub.add_argument('--' + flag, required=True)
        else:
            sub.add_argument('--set-id', required=True)
        if name in ('descriptor', 'checkpoint'):
            sub.add_argument('--kind', choices=('plan', 'selection'), required=True)
        if name == 'checkpoint':
            for flag in ('commit', 'remote', 'branch', 'path'):
                sub.add_argument('--' + flag, required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'init':
            value = initialize(args.registry, args.plan, args.repo, args.binary, args.manifest)
        else:
            with Runner(args.registry, args.set_id) as runner:
                if args.command == 'descriptor':
                    runner.verify()
                    print(runner.descriptor(args.kind).decode(), end='')
                    return 0
                if args.command == 'checkpoint':
                    runner.verify()
                    value = runner.checkpoint(args.kind, args.commit, args.remote, args.branch, args.path)
                elif args.command == 'step': value = runner.step()
                else: value = runner.verify()
        print(encode(value).decode(), end='')
        return 0 if value['state'] != 'blocked' else 1
    except (Exception, KeyboardInterrupt):
        # Never interpolate exception text, local paths, engine logs or numeric performance.
        print(encode({'state': 'blocked'}).decode(), end='')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
