#!/usr/bin/env python3
"""#61: private bounded overlap refresh; never revise the immutable base."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import stat
from pathlib import Path
import time

try:
    import prepare_toss as p
except ModuleNotFoundError:
    from tools import prepare_toss as p

transport = p.transport
POLICY = 'overlap200_prefix_carried_v1'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decoded(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise p.Blocked('invalid_json')
            result[key] = value
        return result
    def invalid(_):
        raise p.Blocked('invalid_json')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError):
        raise p.Blocked('invalid_json') from None


def private_file(path, *, missing=False):
    path = p.private_path(path, exists=not missing or Path(path).exists())
    if path.exists() and path.stat().st_nlink != 1:
        raise p.Blocked('unsafe_file_permissions')
    return path


def public_file(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise p.Blocked('unsafe_path')
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise p.Blocked('symlink_path')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise p.Blocked('unsafe_file_permissions')
    return path


def secure_tree(root):
    # Includes original raw/log references: an unused unsafe member is not a safe snapshot.
    p.private_path(root / '.permission-probe', exists=False)
    for path in root.iterdir():
        if path.is_symlink():
            raise p.Blocked('symlink_path')
        if path.is_dir():
            secure_tree(path)
        else:
            private_file(path)


def csv_rows(raw, expected_hash, start, cutoff):
    try:
        if digest(raw) != expected_hash:
            raise ValueError()
        reader = csv.reader(io.StringIO(raw.decode('utf-8'), newline=''), strict=True)
        if next(reader) != ['date', 'open', 'high', 'low', 'close', 'volume']:
            raise ValueError()
        rows = []
        for row in reader:
            if len(row) != 6 or not start.isoformat() <= row[0] < cutoff.isoformat():
                raise ValueError()
            p.iso_date(row[0])
            o, h, l, c, v = map(float, row[1:])
            if (not all(math.isfinite(n) for n in (o, h, l, c, v)) or min(o, h, l, c) <= 0
                    or v < 0 or not l <= min(o, c) <= max(o, c) <= h):
                raise ValueError()
            rows.append((row[0], o, h, l, c, v))
        p.validate_rows(rows, cutoff)
        return rows
    except (ValueError, TypeError, StopIteration, csv.Error, p.Blocked):
        raise p.Blocked('invalid_base_csv') from None


def validate_base(base, instruments, universe_raw, start, cutoff, now, root):
    """Validate every configured identity and all CSV content before acquiring a token."""
    def require(condition):
        if not condition:
            raise p.Blocked('invalid_base_metadata')
    try:
        fields = {'schema_version', 'provider', 'adjusted', 'timezone', 'cutoff_exclusive',
                  'prepared_at', 'status', 'entries', 'start_date', 'http_attempts',
                  'quality', 'provenance', 'universe'}
        require(isinstance(base, dict) and set(base) == fields)
        require(type(base['schema_version']) is int and base['schema_version'] == 3
                and base['provider'] == 'toss' and base['adjusted'] is True
                and base['timezone'] == 'Asia/Seoul' and base['status'] == 'complete'
                and base['start_date'] == start.isoformat())
        base_cutoff = p.iso_date(base['cutoff_exclusive'])
        prepared = p.timestamp(base['prepared_at'])
        require(start < base_cutoff < cutoff and prepared <= now
                and prepared.astimezone(p.KST).date() >= base_cutoff)
        require(base['universe'] == dict(path='universe.json', sha256=digest(universe_raw)))
        require((root / 'universe.json').read_bytes() == universe_raw)
        require(type(base['http_attempts']) is int and base['http_attempts'] >= 0)
        quality = base['quality']
        expected = dict(exchange_calendar_guarantee=False, is_end=p.BOUNDARY.isoformat(),
                        min_total_rows_exclusive=500, min_rows_each_side=2, max_end_gap_calendar_days=7,
                        calendar_limitation='No authoritative exchange calendar: holidays, missing interior sessions, historical suspensions and early closes are not certified. Weekday checks are not proof of completeness.',
                        completion_policy='US 20:15 America/New_York; KR integrated 20:15 Asia/Seoul; conservative post-extended-session delay, not provider finality guarantee; cutoff exclusive; DST-aware local-midnight daily stamps',
                        history_start_policy='Later observed starts accepted; not independently certified listing dates')
        require(set(quality) == set(expected))
        require(all(type(quality[k]) is type(v) and quality[k] == v for k, v in expected.items()))
        provenance = base['provenance']
        require(isinstance(provenance, dict))
        if set(provenance) in ({'raw_directory', 'request_log', 'scope'}, {'raw_directory', 'request_log', 'refresh'}):
            require(provenance['raw_directory'] == 'raw' and provenance['request_log'] == 'requests.jsonl')
            require((root / 'raw').is_dir())
            private_file(root / 'requests.jsonl')
            if 'scope' in provenance:
                require(provenance['scope'] == 'oauth token issuance and daily candles only')
            else:
                refresh = provenance['refresh']
                require(isinstance(refresh, dict) and refresh['policy'] == POLICY
                        and re.fullmatch(r'[0-9a-f]{64}', refresh['base_manifest_sha256']) is not None)
                previous = private_file(refresh['base_manifest_path'])
                require(digest(previous.read_bytes()) == refresh['base_manifest_sha256'])
                require(refresh['base_provider'] == 'toss'
                        and p.timestamp(refresh['base_prepared_at']) <= prepared
                        and p.iso_date(refresh['base_cutoff_exclusive']) < base_cutoff)
        elif set(provenance) == {'batch_manifests', 'plan_sha256', 'reserved_attempts'}:
            require(re.fullmatch(r'[0-9a-f]{64}', provenance['plan_sha256']) is not None
                    and type(provenance['reserved_attempts']) is int
                    and provenance['reserved_attempts'] >= base['http_attempts'])
            require(isinstance(provenance['batch_manifests'], list) and bool(provenance['batch_manifests']))
            for link in provenance['batch_manifests']:
                require(set(link) == {'path', 'sha256'} and isinstance(link['path'], str)
                        and re.fullmatch(r'batches/[0-9]{4}/manifest\.json', link['path']) is not None)
                require(digest(private_file(root / link['path']).read_bytes()) == link['sha256'])
        else:
            require(False)
        entries = base['entries']
        require(isinstance(entries, list) and len(entries) == len(instruments))
        by_key = {(e['market'], e['ticker']): e for e in entries}
        require(len(by_key) == len(entries) and set(by_key) == {(i['market'], i['ticker']) for i in instruments})
        result, paths = {}, set()
        for instrument in instruments:
            key = instrument['market'], instrument['ticker']
            entry = by_key[key]
            require(set(entry) == {'market', 'ticker', 'source_symbol', 'currency', 'session', 'path', 'sha256',
                                  'rows', 'first', 'last', 'quality', 'observed_history_start', 'starts_after_requested_start'})
            us = instrument['market'] == 'US'
            require(entry['source_symbol'] == instrument['source_symbol']
                    and entry['currency'] == ('USD' if us else 'KRW')
                    and entry['session'] == ('US_REGULAR' if us else 'KR_INTEGRATED'))
            eq = entry['quality']
            require(set(eq) == {'pages', 'duplicate_boundaries', 'incomplete_excluded', 'dedup_policy'})
            require(all(type(eq[k]) is int and eq[k] >= (1 if k == 'pages' else 0)
                        for k in ('pages', 'duplicate_boundaries', 'incomplete_excluded')))
            require(eq['dedup_policy'] == 'identical first-row overlap with previous oldest only')
            name = entry['path']
            if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_./-]*\.csv', name)
                    or any(part in ('', '.', '..') for part in name.split('/')) or name in paths):
                raise p.Blocked('unsafe_base_path')
            paths.add(name)
            raw = private_file(root / name).read_bytes()
            rows = csv_rows(raw, entry['sha256'], start, base_cutoff)
            zone = p.ZoneInfo('America/New_York') if us else p.KST
            require(dt.datetime.combine(p.iso_date(rows[-1][0]), dt.time(20, 15), zone) <= prepared)
            require(type(entry['rows']) is int and entry['rows'] == len(rows)
                    and entry['first'] == rows[0][0] and entry['last'] == rows[-1][0]
                    and entry['observed_history_start'] == rows[0][0]
                    and type(entry['starts_after_requested_start']) is bool
                    and entry['starts_after_requested_start'] == (rows[0][0] > start.isoformat()))
            result[key] = rows
        if 'refresh' in provenance:
            symbols = provenance['refresh']['symbols']
            require(isinstance(symbols, list) and len(symbols) == len(entries))
            require({(s['market'], s['ticker']) for s in symbols} == set(by_key))
            for symbol in symbols:
                entry = by_key[(symbol['market'], symbol['ticker'])]
                require(set(symbol) == {'market', 'ticker', 'source_symbol', 'mode', 'first', 'last', 'rows',
                                        'base_coverage', 'tail_coverage', 'overlap_rows', 'prefix_carried', 'appended_rows'})
                require(all(type(symbol[k]) is type(entry[k]) and symbol[k] == entry[k]
                            for k in ('source_symbol', 'first', 'last', 'rows')))
                require(symbol['mode'] in ('append', 'unchanged', 'full-refresh')
                        and type(symbol['prefix_carried']) is bool
                        and symbol['prefix_carried'] == (symbol['mode'] != 'full-refresh'))
                require(type(symbol['overlap_rows']) is int and 0 <= symbol['overlap_rows'] <= 200
                        and type(symbol['appended_rows']) is int and 0 <= symbol['appended_rows'] <= symbol['rows'])
                carried, fresh = symbol['base_coverage'], symbol['tail_coverage']
                require(set(carried) == {'first', 'last', 'rows', 'prepared_at'}
                        and type(carried['rows']) is int and carried['rows'] > 500
                        and start <= p.iso_date(carried['first']) <= p.iso_date(carried['last']) < base_cutoff
                        and carried['prepared_at'] == provenance['refresh']['base_prepared_at'])
                require(set(fresh) == {'first', 'last', 'rows'} and type(fresh['rows']) is int and 0 <= fresh['rows'] <= 200)
                require((fresh['rows'] == 0 and fresh['first'] is None and fresh['last'] is None)
                        or (fresh['rows'] > 0 and start <= p.iso_date(fresh['first']) <= p.iso_date(fresh['last']) < base_cutoff))
                if symbol['prefix_carried']:
                    require(symbol['overlap_rows'] >= 2 and symbol['rows'] == carried['rows'] + symbol['appended_rows']
                            and (symbol['appended_rows'] == 0) == (symbol['mode'] == 'unchanged'))
        return result
    except p.Blocked as error:
        if str(error) in ('invalid_base_csv', 'unsafe_base_path', 'unsafe_file_permissions',
                          'symlink_path', 'git_checkout_path', 'unsafe_directory_permissions'):
            raise
        raise p.Blocked('invalid_base_metadata') from None
    except (KeyError, TypeError, ValueError, StopIteration):
        raise p.Blocked('invalid_base_metadata') from None


def recheck_base(pins):
    for path, expected in pins.items():
        if digest(private_file(path).read_bytes()) != expected:
            raise p.Blocked('base_changed')


class CheckedAuth(p.Auth):
    """Original Auth and Client; add the same optional identity checks on every page."""
    def candles(self, params):
        response = super().candles(params)
        result = response.get('result')
        if not isinstance(result, dict) or not isinstance(result.get('candles'), list):
            raise p.Blocked('invalid_candle_response')
        for obj in [response, result, *result['candles']]:
            if not isinstance(obj, dict):
                raise p.Blocked('invalid_candle')
            for key in ('symbol', 'interval', 'adjusted'):
                if key in obj:
                    expected = True if key == 'adjusted' else params[key]
                    value = obj[key]
                    if type(value) is not type(expected) or value != expected:
                        raise p.Blocked('candle_metadata_mismatch')
        return response


def tail(auth, instrument, start, cutoff, now):
    before = cutoff.isoformat() + 'T00:00:00+09:00'
    response = auth.candles(dict(symbol=instrument['source_symbol'], interval='1d', count=200,
                                before=before, adjusted='true'))
    result = response['result']
    candles = result['candles']
    if not isinstance(candles, list) or len(candles) > 200:
        raise p.Blocked('invalid_page')
    rows, previous, excluded = [], None, 0
    for candle in candles:
        when = p.timestamp(candle.get('timestamp'))
        if when > p.timestamp(before) or (previous is not None and when >= previous):
            raise p.Blocked('nondecreasing_page_timestamps')
        previous = when
        row = p.normalize(candle, instrument['market'], now)
        if row is None:
            excluded += 1
        elif start.isoformat() <= row[0] < cutoff.isoformat():
            rows.append(row)
    cursor = result.get('nextBefore')
    if cursor is not None and (not candles or p.timestamp(cursor) >= p.timestamp(before)
                               or p.timestamp(cursor) > previous):
        raise p.Blocked('cursor_without_progress')
    return list(reversed(rows)), dict(pages=1, duplicate_boundaries=0, incomplete_excluded=excluded,
                                     dedup_policy='identical first-row overlap with previous oldest only')


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise p.Blocked('invalid_arguments')


def main(argv=None, *, send=transport, now=None, monotonic=time.monotonic, sleep=time.sleep):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    for flag in ('universe-file', 'universe-sha256', 'base-manifest', 'base-sha256',
                 'env-file', 'token-file', 'output', 'start-date', 'cutoff-exclusive'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--max-attempts', type=int, default=600)
    parser.add_argument('--max-minutes', type=float, default=20)
    parser.add_argument('--min-interval', type=float, default=.25)
    output, client, current, args = None, None, None, None
    entries, lineage = [], []
    now = now or dt.datetime.now(p.KST)
    epoch = monotonic()
    try:
        args = parser.parse_args(argv)
        if (not 1 <= args.max_attempts <= 600 or not math.isfinite(args.max_minutes)
                or not 0 < args.max_minutes <= 20 or not math.isfinite(args.min_interval)
                or args.min_interval < .25):
            raise p.Blocked('invalid_budget')
        if not all(re.fullmatch(r'[0-9a-f]{64}', pin) for pin in (args.base_sha256, args.universe_sha256)):
            raise p.Blocked('invalid_sha256')
        start, cutoff = p.iso_date(args.start_date), p.iso_date(args.cutoff_exclusive)
        if now.tzinfo is None or start >= cutoff or cutoff > now.astimezone(p.KST).date():
            raise p.Blocked('invalid_date_range')
        universe_raw = public_file(args.universe_file).read_bytes()
        if digest(universe_raw) != args.universe_sha256:
            raise p.Blocked('universe_hash_mismatch')
        try:
            instruments = p.validate_universe(universe_raw)['instruments']
            if {i['market'] for i in instruments} != {'US', 'KR'}:
                raise ValueError()
        except (ValueError, TypeError, RecursionError):
            raise p.Blocked('invalid_universe') from None
        base_path = private_file(args.base_manifest)
        secure_tree(base_path.parent)
        base_raw = base_path.read_bytes()
        if digest(base_raw) != args.base_sha256:
            raise p.Blocked('base_hash_mismatch')
        base = decoded(base_raw)
        candidate = p.private_path(args.output, exists=False)
        if candidate.exists():
            raise p.Blocked('output_already_exists')
        token = private_file(args.token_file, missing=True)
        for suffix in ('.collection.lock', '.issuance.lock'):
            private_file(token.with_name(token.name + suffix), missing=True)
        private_file(args.env_file)
        if any(base_path.parent == path or base_path.parent in path.parents
               for path in (candidate, token, Path(args.env_file))):
            raise p.Blocked('mutable_base_path')
        credentials = p.read_env(args.env_file)
        old_rows = validate_base(base, instruments, universe_raw, start, cutoff, now, base_path.parent)
        pins = {base_path: args.base_sha256, base_path.parent / 'universe.json': args.universe_sha256}
        pins.update({base_path.parent / e['path']: e['sha256'] for e in base['entries']})
        recheck_base(pins)
        evidence_pins = {f: digest(private_file(f).read_bytes()) for f in base_path.parent.rglob('*') if f.is_file()}
        candidate.mkdir(mode=0o700)
        output = candidate
        p.immutable(output / 'universe.json', universe_raw)
        client = p.Client(output, args.max_attempts, args.max_minutes * 60, args.min_interval,
                          send, monotonic, sleep)
        client.deadline = epoch + args.max_minutes * 60
        with p.file_lock(token.with_name(token.name + '.collection.lock'), client):
            auth = CheckedAuth(client, token, credentials)
            for instrument in instruments:
                current = {k: instrument[k] for k in ('market', 'ticker')}
                old = old_rows[(current['market'], current['ticker'])]
                fresh, quality = tail(auth, instrument, start, cutoff, now)
                recheck_base(pins)
                fresh_by_day = {r[0]: r for r in fresh}
                overlap = [r for r in old if r[0] in fresh_by_day]
                old_by_day = {r[0]: r for r in old}
                matches = (len(overlap) >= 2 and old[-1][0] in fresh_by_day
                           and all(r == fresh_by_day[r[0]] for r in overlap)
                           and all(r[0] in fresh_by_day for r in old if fresh[0][0] <= r[0] <= fresh[-1][0])
                           and all(r[0] in old_by_day for r in fresh if old[0][0] <= r[0] <= old[-1][0]))
                if matches:
                    rows = old + [r for r in fresh if r[0] > old[-1][0]]
                    mode = 'append' if len(rows) > len(old) else 'unchanged'
                else:
                    rows, quality = p.history(auth, current['market'], current['ticker'], start, cutoff, now,
                                              source_symbol=instrument['source_symbol'])
                    mode = 'full-refresh'
                p.validate_rows(rows, cutoff)
                if rows[0][0] > old[0][0] or rows[-1][0] < max(old[-1][0], fresh[-1][0] if fresh else old[-1][0]):
                    raise p.Blocked('history_coverage_regressed')
                buffer = io.StringIO(newline='')
                writer = csv.writer(buffer, lineterminator='\n')
                if mode == 'full-refresh':
                    writer.writerow(('date', 'open', 'high', 'low', 'close', 'volume'))
                    writer.writerows(rows)
                    raw = buffer.getvalue().encode()
                else:
                    old_entry = next(e for e in base['entries'] if (e['market'], e['ticker']) == (current['market'], current['ticker']))
                    raw = private_file(base_path.parent / old_entry['path']).read_bytes()
                    writer.writerows(rows[len(old):])
                    if len(rows) > len(old):
                        raw += (b'' if raw.endswith(b'\n') else b'\n') + buffer.getvalue().encode()
                name = f"{current['market']}_{current['ticker']}.toss.csv"
                p.immutable(output / name, raw)
                us = current['market'] == 'US'
                entries.append(dict(current, source_symbol=instrument['source_symbol'], currency='USD' if us else 'KRW',
                                    session='US_REGULAR' if us else 'KR_INTEGRATED', path=name, sha256=digest(raw),
                                    rows=len(rows), first=rows[0][0], last=rows[-1][0], quality=quality,
                                    observed_history_start=rows[0][0], starts_after_requested_start=rows[0][0] > start.isoformat()))
                lineage.append(dict(current, source_symbol=instrument['source_symbol'], mode=mode,
                                    first=rows[0][0], last=rows[-1][0], rows=len(rows),
                                    base_coverage=dict(first=old[0][0], last=old[-1][0], rows=len(old),
                                                       prepared_at=base['prepared_at']),
                                    tail_coverage=dict(first=fresh[0][0] if fresh else None,
                                                       last=fresh[-1][0] if fresh else None, rows=len(fresh)),
                                    overlap_rows=len(overlap), prefix_carried=mode != 'full-refresh',
                                    appended_rows=sum(r[0] > old[-1][0] for r in rows)))
            refresh = dict(policy=POLICY, base_manifest_sha256=args.base_sha256,
                           base_manifest_path=str(base_path),
                           base_provider=base['provider'], base_prepared_at=base['prepared_at'],
                           base_cutoff_exclusive=base['cutoff_exclusive'], symbols=lineage,
                           prefix_vintage='Carried older prefix retains its earlier/mixed acquisition vintage; follow immutable base lineage. Base prepared_at is not a uniform prefix acquisition date; not entire history as of today.',
                           revision_limitation='Supplier revisions outside the 200-bar overlap are not certified; no PIT, total-return, calendar or listing certification.')
            manifest = dict(base, cutoff_exclusive=cutoff.isoformat(), prepared_at=now.isoformat(), entries=entries,
                            http_attempts=client.attempts, provenance=dict(raw_directory='raw', request_log='requests.jsonl', refresh=refresh))
            recheck_base(pins)
            if client.clock() >= client.deadline:
                raise p.Blocked('wall_budget_exhausted')
            secure_tree(base_path.parent)
            if {f for f in base_path.parent.rglob('*') if f.is_file()} != set(evidence_pins):
                raise p.Blocked('base_changed')
            recheck_base(evidence_pins)
            secure_tree(output)
            if (private_file(output / 'universe.json').read_bytes() != universe_raw
                    or any(digest(private_file(output / e['path']).read_bytes()) != e['sha256'] for e in entries)):
                raise p.Blocked('output_changed')
            if client.clock() >= client.deadline:
                raise p.Blocked('wall_budget_exhausted')
            p.immutable(output / 'manifest.json', p.json_bytes(manifest))
        print(f'complete: {len(entries)} entries; private manifest.json written')
        return 0
    except (Exception, KeyboardInterrupt) as error:
        code = str(error) if isinstance(error, p.Blocked) else 'interrupted' if isinstance(error, KeyboardInterrupt) else 'invalid_state'
        if output is not None and args is not None:
            try:
                p.immutable(output / 'blocked.json', p.json_bytes(dict(schema_version=3, provider='toss', status='blocked',
                            prepared_at=now.isoformat(), universe=dict(path='universe.json', sha256=args.universe_sha256),
                            provenance=dict(raw_directory='raw', request_log='requests.jsonl',
                                            refresh=dict(policy=POLICY, base_manifest_sha256=args.base_sha256,
                                                         base_manifest_path=args.base_manifest, symbols=lineage)),
                            errors=[dict(current or {}, code=code)], completed_entries=entries,
                            http_attempts=client.attempts if client else 0)))
            except OSError:
                code = 'blocked_record_write_failed'
        print('blocked: ' + code)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
