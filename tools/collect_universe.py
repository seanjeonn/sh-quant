#!/usr/bin/env python3
"""#57: bounded initial acquisition, private immutable evidence, explicit resume."""
import argparse
import csv
import ctypes
import errno
import datetime as dt
import fcntl
import io
import hashlib
import json
import math
import os
import signal
import stat
from pathlib import Path
import subprocess
import sys
import time

TOOLS = Path(__file__).resolve().parent


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, indent=2).encode()


def decoded(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Blocked('invalid_json')
            result[key] = value
        return result
    def constant(value):
        raise Blocked('invalid_json')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def checked_path(value, *, private=True, missing=False):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise Blocked('unsafe_path')
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise Blocked('symlink_path')
        if private and os.path.lexists(ancestor / '.git'):
            raise Blocked('git_checkout_path')
    if private:
        parent = path.parent.stat()
        if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700:
            raise Blocked('unsafe_directory_permissions')
    if missing and not path.exists():
        return path
    info = path.lstat()
    if info.st_uid != os.getuid():
        raise Blocked('unsafe_owner')
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink != 1 or (private and stat.S_IMODE(info.st_mode) != 0o600):
            raise Blocked('unsafe_file_permissions')
    elif stat.S_ISDIR(info.st_mode):
        if not private or stat.S_IMODE(info.st_mode) != 0o700:
            raise Blocked('unsafe_directory_permissions')
    else:
        raise Blocked('unsafe_file_type')
    return path


def secure_tree(path):
    checked_path(path)
    for item in path.iterdir():
        checked_path(item)
        if item.is_dir():
            secure_tree(item)


def read_private(path):
    checked_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Blocked('unsafe_file_type')
        return stream.read()


def immutable(path, raw):
    checked_path(path, missing=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def source_identity(child):
    # Passive, relevant Python only: Rust builds/edits must not invalidate a plan.
    paths = {TOOLS / 'collect_universe.py', TOOLS / 'prepare_toss.py', child}
    helper = TOOLS / 'universe_contract.py'
    if helper.exists():
        paths.add(helper)
    return {str(path): digest(path.read_bytes()) for path in sorted(paths)}


def load_catalog(raw):
    from universe_contract import validate_universe
    catalog = validate_universe(raw)
    if {i['market'] for i in catalog['instruments']} != {'US', 'KR'}:
        raise Blocked('both_markets_required')
    return catalog


def batch_catalogs(catalog, size):
    result = []
    for offset in range(0, len(catalog['instruments']), size):
        subset = dict(catalog)
        subset['universe_id'] = catalog['universe_id'][:58] + '-b' + f'{len(result):04d}'
        subset['instruments'] = catalog['instruments'][offset:offset + size]
        result.append(encoded(subset))
    return result


def validate_batch(batch, subset, plan, reserved):
    """Recheck data, not just a child's success code or a cached root manifest."""
    secure_tree(batch)
    raw = read_private(batch / 'manifest.json')
    manifest = decoded(raw)
    expected = {'schema_version': 3, 'provider': 'toss', 'adjusted': True,
                'timezone': 'Asia/Seoul', 'status': 'complete',
                'start_date': plan['start_date'], 'cutoff_exclusive': plan['cutoff_exclusive'],
                'universe': {'path': 'universe.json', 'sha256': digest(subset)}}
    if (type(manifest.get('schema_version')) is not int or type(manifest.get('adjusted')) is not bool
            or any(manifest.get(k) != v for k, v in expected.items())):
        raise Blocked('invalid_child_manifest')
    if read_private(batch / 'universe.json') != subset:
        raise Blocked('child_catalog_changed')
    instruments = decoded(subset)['instruments']
    entries = manifest['entries']
    if len(entries) != len(instruments):
        raise Blocked('incomplete_child')
    attempts = manifest['http_attempts']
    if type(attempts) is not int or not 0 <= attempts <= reserved:
        raise Blocked('invalid_child_attempts')
    fields = {'market', 'ticker', 'source_symbol', 'currency', 'session', 'path',
              'sha256', 'rows', 'first', 'last', 'quality', 'observed_history_start',
              'starts_after_requested_start'}
    paths = set()
    for entry, instrument in zip(entries, instruments):
        if set(entry) != fields or any(entry[k] != instrument[k] for k in ('market', 'ticker', 'source_symbol')):
            raise Blocked('child_entry_mismatch')
        us = entry['market'] == 'US'
        if (entry['currency'] != ('USD' if us else 'KRW')
                or entry['session'] != ('US_REGULAR' if us else 'KR_INTEGRATED')):
            raise Blocked('child_entry_mismatch')
        name = entry['path']
        if (not isinstance(name, str) or not name or Path(name).is_absolute()
                or any(p in ('', '.', '..') for p in name.split('/')) or name in paths):
            raise Blocked('unsafe_child_path')
        paths.add(name)
        csvraw = read_private(batch / name)
        if digest(csvraw) != entry['sha256']:
            raise Blocked('csv_hash_changed')
        reader = csv.reader(io.StringIO(csvraw.decode('utf-8'), newline=''))
        if next(reader) != ['date', 'open', 'high', 'low', 'close', 'volume']:
            raise Blocked('invalid_csv')
        rows = list(reader)
        days = []
        for row in rows:
            if len(row) != 6:
                raise Blocked('invalid_csv')
            day = dt.date.fromisoformat(row[0])
            if day.isoformat() != row[0] or not plan['start_date'] <= row[0] < plan['cutoff_exclusive']:
                raise Blocked('invalid_csv_date')
            o, h, l, c, v = map(float, row[1:])
            if (not all(math.isfinite(n) for n in (o, h, l, c, v)) or min(o, h, l, c) <= 0
                    or v < 0 or not l <= min(o, c) <= max(o, c) <= h):
                raise Blocked('invalid_csv_ohlcv')
            days.append(day)
        boundary = dt.date(2022, 12, 31)
        cutoff = dt.date.fromisoformat(plan['cutoff_exclusive'])
        if (len(rows) <= 500 or type(entry['rows']) is not int or entry['rows'] != len(rows)
                or any(a >= b for a, b in zip(days, days[1:]))
                or sum(d <= boundary for d in days) < 2 or sum(d > boundary for d in days) < 2
                or (cutoff - days[-1]).days > 7 or entry['first'] != rows[0][0]
                or entry['last'] != rows[-1][0] or entry['observed_history_start'] != rows[0][0]
                or type(entry['starts_after_requested_start']) is not bool
                or entry['starts_after_requested_start'] != (rows[0][0] > plan['start_date'])):
            raise Blocked('invalid_csv_coverage')
    return manifest, raw


def wait_owned(process, seconds):
    """Keep the owned leader unreaped until its whole group is terminated.

    poll()/wait() would reap it first, permitting PID/PGID reuse before cleanup.
    macOS Python omits os.waitid; libc's POSIX WNOWAIT supplies the same fence.
    No siginfo layout is interpreted: a zero buffer means no child event.
    """
    waitid = ctypes.CDLL(None, use_errno=True).waitid
    waitid.argtypes = (ctypes.c_int, ctypes.c_uint, ctypes.c_void_p, ctypes.c_int)
    waitid.restype = ctypes.c_int
    deadline = time.monotonic() + seconds
    while True:
        info = ctypes.create_string_buffer(256)
        result = waitid(os.P_PID, process.pid, info, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if result != 0:
            if ctypes.get_errno() == errno.EINTR:
                continue
            raise Blocked('child_wait_failed')
        if any(info.raw):
            # The unreaped direct child still owns this PID: never a cached-PID kill.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # Darwin reports EPERM for an exited group with only its zombie leader;
                # same-UID living descendants make the owned group signalable.
                pass
            return process.wait()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired('private_child', seconds)
        time.sleep(min(.02, remaining))


def collect(args, child):
    checked_path(args.universe_file, private=False)
    checked_path(args.env_file)
    checked_path(args.token_file, missing=True)
    output = checked_path(args.output, missing=True)
    if args.resume:
        if not output.is_dir():
            raise Blocked('resume_output_missing')
    elif output.exists():
        raise Blocked('output_already_exists')
    else:
        output.mkdir(mode=0o700)
    lock = output / '.collection.lock'
    checked_path(lock, missing=not args.resume)
    flags = os.O_RDWR | os.O_NOFOLLOW
    if not args.resume:
        flags |= os.O_CREAT | os.O_EXCL
    fd = os.open(lock, flags, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked('busy') from None
        os.set_inheritable(fd, True)
        return collect_locked(args, child, fd)
    finally:
        # No LOCK_UN: a live child retains this SAME open file description.
        os.close(fd)


def validate_inventory(output, count):
    names = {f'{n:04d}' for n in range(count)}
    allowed_root = {'.collection.lock', 'universe.json', 'plan.json', 'plan.sha256',
                    'catalogs', 'batches', 'attempts', 'manifest.json'}
    if {p.name for p in output.iterdir()} - allowed_root:
        raise Blocked('ambiguous_state')
    if {p.name for p in (output / 'catalogs').iterdir()} != {n + '.json' for n in names}:
        raise Blocked('ambiguous_state')
    allowed = {n + suffix for n in names for suffix in
               ('.intent.json', '.started.json', '.result.json', '.log.json')}
    attempt_names = {p.name for p in (output / 'attempts').iterdir()}
    batch_names = {p.name for p in (output / 'batches').iterdir()}
    if attempt_names - allowed or batch_names - names:
        raise Blocked('ambiguous_state')
    active = {int(n[:4]) for n in attempt_names} | {int(n) for n in batch_names}
    if active:
        if active != set(range(max(active) + 1)):
            raise Blocked('ambiguous_state')
        for n in range(max(active)):
            receipt = output / 'attempts' / f'{n:04d}.result.json'
            if not receipt.exists() or decoded(read_private(receipt)).get('status') != 'complete':
                raise Blocked('ambiguous_state')
    if (output / 'manifest.json').exists() and len(active) != count:
        raise Blocked('ambiguous_state')


def collect_locked(args, child, lock_fd):
    raw = checked_path(args.universe_file, private=False).read_bytes()
    catalog = load_catalog(raw)
    output = checked_path(args.output, missing=not args.resume)
    checked_path(args.env_file)
    checked_path(args.token_file, missing=True)
    if output.exists():
        secure_tree(output)
    start = dt.date.fromisoformat(args.start_date)
    cutoff = dt.date.fromisoformat(args.cutoff_exclusive)
    if start.isoformat() != args.start_date or cutoff.isoformat() != args.cutoff_exclusive or start >= cutoff:
        raise Blocked('invalid_date_range')
    subsets = batch_catalogs(catalog, args.batch_size)
    plan = dict(schema_version=1, output=str(output), started_epoch=time.time(),
                universe_sha256=digest(raw), source=source_identity(child),
                start_date=args.start_date, cutoff_exclusive=args.cutoff_exclusive,
                max_attempts=args.max_attempts, max_minutes=args.max_minutes,
                batch_size=args.batch_size, batches=[digest(b) for b in subsets])
    if args.resume:
        plan_raw = read_private(output / 'plan.json')
        stored = decoded(plan_raw)
        if (digest(plan_raw) != read_private(output / 'plan.sha256').decode('ascii')
                or not isinstance(stored.get('started_epoch'), (int, float))
                or not math.isfinite(stored['started_epoch'])
                or stored['started_epoch'] > time.time()):
            raise Blocked('plan_changed')
        plan['started_epoch'] = stored['started_epoch']
        if plan != stored or read_private(output / 'universe.json') != raw:
            raise Blocked('plan_changed')
        for number, subset in enumerate(subsets):
            if read_private(output / 'catalogs' / f'{number:04d}.json') != subset:
                raise Blocked('catalog_changed')
    else:
        for name in ('catalogs', 'batches', 'attempts'):
            (output / name).mkdir(mode=0o700)
        immutable(output / 'universe.json', raw)
        immutable(output / 'plan.json', encoded(plan))
        immutable(output / 'plan.sha256', digest(encoded(plan)).encode())
        for number, subset in enumerate(subsets):
            immutable(output / 'catalogs' / f'{number:04d}.json', subset)
    validate_inventory(output, len(subsets))
    entries, links, charged, used = [], [], 0, 0
    last = None
    for number, subset in enumerate(subsets):
        name = f'{number:04d}'
        catalog_path = output / 'catalogs' / (name + '.json')
        batch = output / 'batches' / name
        receipt = output / 'attempts' / (name + '.result.json')
        intent_path = output / 'attempts' / (name + '.intent.json')
        if receipt.exists():
            if decoded(read_private(receipt)).get('status') != 'complete':
                raise Blocked('failed_child')
            intent = decoded(read_private(intent_path))
            if (intent['reserved_attempts'] != min(600, args.max_attempts - charged)
                    or intent['plan_sha256'] != digest(encoded(plan))
                    or intent['catalog_sha256'] != digest(subset) or intent['batch'] != number
                    or not math.isfinite(intent['max_minutes']) or not 0 < intent['max_minutes'] <= 20):
                raise Blocked('intent_changed')
            charged += intent['reserved_attempts']
        else:
            if source_identity(child) != plan['source']:
                raise Blocked('source_changed')
            if intent_path.exists() or batch.exists() or (output / 'attempts' / (name + '.started.json')).exists():
                raise Blocked('incomplete_child')
            attempts = min(600, args.max_attempts - charged)
            minutes = min(20, (plan['started_epoch'] + args.max_minutes * 60 - time.time()) / 60)
            if attempts <= 0 or minutes <= 0:
                raise Blocked('total_budget_exhausted')
            charged += attempts
            intent = dict(batch=number, reserved_attempts=attempts, max_minutes=minutes,
                          plan_sha256=digest(encoded(plan)), catalog_sha256=digest(subset))
            immutable(intent_path, encoded(intent))
            command = [sys.executable, str(child), '--env-file', args.env_file,
                       '--token-file', args.token_file, '--output', str(batch),
                       '--universe-file', str(catalog_path), '--start-date', args.start_date,
                       '--cutoff-exclusive', args.cutoff_exclusive, '--max-attempts', str(attempts),
                       '--max-minutes', str(minutes), '--min-interval', '0.25']
            process = None
            code = None
            try:
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           pass_fds=(lock_fd,), start_new_session=True)
                immutable(output / 'attempts' / (name + '.started.json'),
                          encoded(dict(pid=process.pid, pgid=process.pid, started_epoch=time.time())))
                seconds = min(minutes * 60, plan['started_epoch'] + plan['max_minutes'] * 60 - time.time())
                returncode = wait_owned(process, max(0, seconds))
                if returncode:
                    code = 'child_failed'
            except subprocess.TimeoutExpired:
                code = 'child_timeout'
            except KeyboardInterrupt:
                code = 'interrupted'
            except Exception:
                code = 'child_launch_failed'
            if code:
                if process is not None and process.returncode is None:
                    # Only the process group created by THIS Popen. Never consult cached PIDs.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                failure = encoded(dict(status='blocked', code=code))
                immutable(receipt, failure)
                immutable(output / 'attempts' / (name + '.log.json'), failure)
                raise Blocked(code)
        last, manifest_raw = validate_batch(batch, subset, plan, intent['reserved_attempts'])
        expected_receipt = dict(status='complete', manifest_sha256=digest(manifest_raw),
                                intent_sha256=digest(read_private(intent_path)),
                                started_sha256=digest(read_private(output / 'attempts' / (name + '.started.json'))))
        if receipt.exists():
            stored_receipt = decoded(read_private(receipt))
            if stored_receipt != expected_receipt:
                raise Blocked('child_metadata_changed')
        used += last['http_attempts']
        links.append(dict(path=f'batches/{name}/manifest.json', sha256=digest(manifest_raw)))
        for entry in last['entries']:
            entries.append(dict(entry, path=f'batches/{name}/' + entry['path']))
        if not receipt.exists():
            immutable(receipt, encoded(expected_receipt))
    if source_identity(child) != plan['source']:
        raise Blocked('source_changed')
    manifest = dict(last, entries=entries, universe=dict(path='universe.json', sha256=digest(raw)),
                    http_attempts=used, provenance=dict(batch_manifests=links,
                    plan_sha256=digest(read_private(output / 'plan.json')),
                    reserved_attempts=charged))
    if (output / 'manifest.json').exists():
        if read_private(output / 'manifest.json') != encoded(manifest):
            raise Blocked('root_manifest_changed')
    else:
        immutable(output / 'manifest.json', encoded(manifest))
    print('complete: private manifest.json written')
    return 0


class Blocked(Exception):
    """Internal allowlisted status, never provider or exception text."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise Blocked('invalid_arguments')


def main(argv=None, *, child_script=None):
    parser = SafeParser(description=__doc__)
    for name in ('universe-file', 'env-file', 'token-file', 'output',
                 'start-date', 'cutoff-exclusive'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--max-attempts', type=int, default=6000)
    parser.add_argument('--max-minutes', type=float, default=120)
    parser.add_argument('--batch-size', type=int, default=12)
    parser.add_argument('--resume', action='store_true')
    try:
        args = parser.parse_args(argv)
        if (not 1 <= args.max_attempts <= 6000 or not math.isfinite(args.max_minutes)
                or not 0 < args.max_minutes <= 120 or not 1 <= args.batch_size <= 512):
            raise Blocked('invalid_budget')
        return collect(args, Path(child_script) if child_script else TOOLS / 'prepare_toss.py')
    except (Exception, KeyboardInterrupt) as error:
        code = str(error) if isinstance(error, Blocked) else 'interrupted' if isinstance(error, KeyboardInterrupt) else 'invalid_state'
        print('blocked: ' + code)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
