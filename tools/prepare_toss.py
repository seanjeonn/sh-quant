#!/usr/bin/env python3
"""Issue #26: bounded, private Toss daily preparation (stdlib only).

No account or order endpoints. Raw responses are private provenance, not logs.
All diagnostics are controlled codes; never interpolate provider text/exceptions.
"""
import argparse
from contextlib import contextmanager
import http.client
import signal
import threading
import csv
import datetime as dt
import email.utils
import fcntl
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

try:  # CLI execution and repository/importlib consumers use the same helper.
    from universe_contract import validate_universe
except ModuleNotFoundError:
    from tools.universe_contract import validate_universe


HOST = 'https://openapi.tossinvest.com'
KST = ZoneInfo('Asia/Seoul')


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def immutable(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def json_bytes(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2).encode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Reject even same-host redirects: fixed allowlist remains exact.
        return None


def transport(method, url, headers, body, timeout):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read(32 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read(32 * 1024 * 1024 + 1)


class Unauthorized(Exception):
    pass


class Client:
    def __init__(self, output, max_attempts, max_seconds, min_interval,
                 send=transport, monotonic=time.monotonic, sleep=time.sleep):
        self.output = output
        self.max_attempts = max_attempts
        self.deadline = monotonic() + max_seconds
        self.min_interval = min_interval
        self.send, self.clock, self.sleep = send, monotonic, sleep
        self.attempts = 0
        self.last = None
        (output / 'raw').mkdir(mode=0o700)
        immutable(output / 'requests.jsonl', b'')

    def audit(self, record):
        fd = os.open(self.output / 'requests.jsonl', os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        with os.fdopen(fd, 'a') as f:
            f.write(json.dumps(record, allow_nan=False) + '\n')
            f.flush()
            os.fsync(f.fileno())

    def check(self):
        if self.attempts >= self.max_attempts:
            raise Blocked('attempt_budget_exhausted')
        if self.clock() >= self.deadline:
            raise Blocked('wall_budget_exhausted')

    def wait(self, delay):
        remaining = self.deadline - self.clock()
        if remaining <= 0 or delay >= remaining:
            raise Blocked('wall_budget_exhausted')
        if delay > 0:
            self.sleep(delay)
        self.check()

    def _validate_request(self, path, params, form):
        if path not in ('/oauth2/token', '/api/v1/candles'):
            raise Blocked('endpoint_not_allowed')
        if path == '/api/v1/candles' and params and set(params) - {'symbol', 'interval', 'count', 'before', 'adjusted'}:
            raise Blocked('parameter_not_allowed')

    def request(self, path, params=None, token=None, form=None):
        self._validate_request(path, params, form)
        url = HOST + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        headers = {'Accept': 'application/json', 'Accept-Encoding': 'gzip'}
        body = None
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        for retry in range(5):
            self.check()
            if self.last is not None:
                self.wait(max(0, self.min_interval - (self.clock() - self.last)))
            self.attempts += 1
            number = self.attempts
            self.last = self.clock()
            base = {'attempt': number, 'endpoint': path, 'params': params or {}}
            self.audit(dict(base, event='start', timestamp=stamp()))
            status, response_headers, raw = 0, {}, b''
            network_error = False
            fatal = None
            try:
                timeout = min(30, max(.001, self.deadline - self.clock()))
                with request_deadline(timeout):
                    status, response_headers, raw = self.send('POST' if form is not None else 'GET', url, headers, body, timeout)
            except (OSError, TimeoutError, urllib.error.URLError, http.client.HTTPException):
                network_error = True
            except KeyboardInterrupt:
                fatal = 'interrupted'
            except Exception:
                fatal = 'transport_failure'
            lowered = {k.lower(): v for k, v in response_headers.items()}
            end = dict(base, event='end', timestamp=stamp(), status=status, network_error=network_error,
                       response_received=bool(status))
            if path != '/oauth2/token':
                name = f'raw/{number:06d}.bin'
                immutable(self.output / name, raw)
                end.update(raw_path=name, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            request_id = lowered.get('x-request-id', '')
            if re.fullmatch(r'[a-fA-F0-9-]{8,64}', request_id):
                end['request_id'] = request_id
            self.audit(end)
            if fatal:
                raise Blocked(fatal)
            if self.clock() >= self.deadline:
                raise Blocked('wall_budget_exhausted')
            if len(raw) > 32 * 1024 * 1024:
                raise Blocked('response_too_large')
            if status == 401:
                raise Unauthorized()
            if status == 403:
                raise Blocked('http_403')
            if network_error or status == 429 or 500 <= status < 600:
                delay = min(2 ** retry, 16)
                if 'retry-after' in lowered:
                    try:
                        value = lowered['retry-after']
                        delay = float(value) if re.fullmatch(r'\d+(\.\d+)?', value) else max(0, email.utils.parsedate_to_datetime(value).timestamp() - time.time())
                    except (ValueError, TypeError, OverflowError):
                        raise Blocked('invalid_retry_after') from None
                if retry == 4:
                    raise Blocked('retry_limit')
                self.wait(delay)
                continue
            if status != 200:
                raise Blocked('http_' + str(int(status)))
            try:
                if lowered.get('content-encoding', '').lower() == 'gzip' or raw.startswith(b'\x1f\x8b'):
                    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                        raw = compressed.read(32 * 1024 * 1024 + 1)
                if len(raw) > 32 * 1024 * 1024:
                    raise Blocked('response_too_large')
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise Blocked('invalid_json_shape')
                return value
            except (ValueError, OSError, EOFError, UnicodeError):
                raise Blocked('invalid_json_or_gzip') from None
        raise Blocked('retry_limit')


class Blocked(Exception):
    """Only caller-controlled, non-secret error codes belong here."""


def private_path(path, exists=True):
    p = Path(path)
    if not p.is_absolute() or '..' in p.parts:
        raise Blocked('unsafe_path')
    for item in [p, *p.parents]:
        if item.is_symlink():
            raise Blocked('symlink_path')
        if item.is_dir() and (item / '.git').exists():
            raise Blocked('git_checkout_path')
    if exists:
        if not p.exists():
            raise Blocked('missing_private_file')
        s = p.stat()
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o600:
            raise Blocked('unsafe_file_permissions')
    # Parent holding private files must itself be private and owned.
    parent = p.parent
    if parent.exists():
        s = parent.stat()
        if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o700:
            raise Blocked('unsafe_directory_permissions')
    return p


@contextmanager
def request_deadline(seconds):
    # socket timeout alone does not bound a continuously dribbling response.
    if threading.current_thread() is not threading.main_thread():
        raise Blocked('main_thread_required_for_deadline')
    previous = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer[0] > 0:
        raise Blocked('existing_alarm_conflict')
    def expired(signum, frame):
        raise TimeoutError()
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@contextmanager
def file_lock(path, budget):
    p = private_path(path, exists=Path(path).exists())
    fd = os.open(p, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        while True:
            budget.check()
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                budget.wait(.1)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class Auth:
    def __init__(self, client, token_file, credentials):
        self.client, self.token_file, self.credentials = client, Path(token_file), credentials
        self.refreshed = False
        self.token = None

    def get_token(self, rejected=None):
        # Stable sidecar inode serializes issuance even across atomic token replacements.
        lock = self.token_file.with_name(self.token_file.name + '.issuance.lock')
        with file_lock(lock, self.client):
            cached = None
            if self.token_file.exists():
                private_path(self.token_file)
                try:
                    cached = json.loads(self.token_file.read_text())
                    expiry = float(cached['expires_at'])
                    token = cached['access_token']
                    if not isinstance(token, str) or not token or any(c in token for c in '\r\n\x00') or not math.isfinite(expiry):
                        raise ValueError()
                except (ValueError, TypeError, KeyError, OSError):
                    raise Blocked('invalid_token_cache') from None
                if expiry > time.time() and token != rejected:
                    self.token = token
                    return token
            try:
                value = self.client.request('/oauth2/token', form={
                    'grant_type': 'client_credentials', 'client_id': self.credentials['TOSS_CLIENT_ID'],
                    'client_secret': self.credentials['TOSS_CLIENT_SECRET']})
            except Unauthorized:
                raise Blocked('auth_http_401') from None
            try:
                token = value['access_token']
                lifetime = float(value['expires_in'])
                if not isinstance(token, str) or not token or any(c in token for c in '\r\n\x00') or not math.isfinite(lifetime) or lifetime <= 0:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise Blocked('invalid_auth_response') from None
            import secrets
            temp = self.token_file.with_name('.token-' + secrets.token_hex(16))
            immutable(temp, json_bytes({'access_token': token, 'expires_at': time.time() + lifetime}))
            try:
                # Re-check before replacement; never follow a changed credential symlink.
                private_path(self.token_file, exists=self.token_file.exists())
                os.replace(temp, self.token_file)
            finally:
                if temp.exists():
                    temp.unlink()
            self.token = token
            return token

    def candles(self, params):
        token = self.get_token()
        try:
            return self.client.request('/api/v1/candles', params, token=token)
        except Unauthorized:
            if self.refreshed:
                raise Blocked('repeated_http_401') from None
            self.refreshed = True
            token = self.get_token(rejected=token)
            try:
                return self.client.request('/api/v1/candles', params, token=token)
            except Unauthorized:
                raise Blocked('repeated_http_401') from None


UNIVERSE = {
    'US': ('SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'JPM', 'XOM', 'JNJ', 'BRK-B'),
    'KR': ('069500', '005930', '000660', '207940', '005380', '000270', '035420', '051910', '006400', '105560', '055550', '035720'),
}
BOUNDARY = dt.date(2022, 12, 31)


def timestamp(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed
    except (ValueError, TypeError, OverflowError):
        raise Blocked('invalid_timestamp') from None


def normalize(candle, market, now):
    try:
        zone = ZoneInfo('America/New_York') if market == 'US' else KST
        when = timestamp(candle['timestamp'])
        local = when.astimezone(zone)
        if local.time() != dt.time(0):
            raise Blocked('daily_stamp_not_market_midnight')
        day = local.date()
        if when.astimezone(KST).date() != day:
            raise Blocked('daily_stamp_date_mismatch')
        if candle['currency'] != ('USD' if market == 'US' else 'KRW'):
            raise Blocked('currency_mismatch')
        numbers = []
        for key in ('openPrice', 'highPrice', 'lowPrice', 'closePrice', 'volume'):
            value = candle[key]
            if value is None or isinstance(value, bool):
                raise Blocked('invalid_ohlcv')
            numbers.append(float(value))
        o, h, l, c, v = numbers
        if not all(math.isfinite(x) for x in numbers) or min(o, h, l, c) <= 0 or v < 0 or not l <= min(o, c) <= max(o, c) <= h:
            raise Blocked('invalid_ohlcv')
        # Volume may include extended hours: conservatively wait until 20:15
        # local time, not 16:15 regular close. This is not a provider finality guarantee.
        close = dt.time(20, 15)
        completed = dt.datetime.combine(day, close, zone)
        if now.astimezone(dt.timezone.utc) < completed.astimezone(dt.timezone.utc):
            return None
        return (day.isoformat(), o, h, l, c, v)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise Blocked('invalid_candle') from None


def provider_symbol(market, ticker):
    # Explicit identity mapping, NOT ticker normalization. Toss GET /stocks
    # verified BRK.B while the existing Yahoo/research ID remains BRK-B.
    return {('US', 'BRK-B'): 'BRK.B'}.get((market, ticker), ticker)


def history(auth, market, ticker, start, cutoff, now, *, source_symbol=None):
    before = cutoff.isoformat() + 'T00:00:00+09:00'
    cursors, dates = set(), {}
    previous_oldest = None
    duplicates = 0
    pages = 0
    excluded = 0
    while True:
        if before in cursors:
            raise Blocked('cursor_cycle')
        cursors.add(before)
        response = auth.candles({'symbol': provider_symbol(market, ticker) if source_symbol is None else source_symbol, 'interval': '1d', 'count': 200,
                                 'before': before, 'adjusted': 'true'})
        try:
            result = response['result']
            candles = result['candles']
            next_before = result.get('nextBefore')
        except (KeyError, TypeError, AttributeError):
            raise Blocked('invalid_candle_response') from None
        if not isinstance(candles, list) or len(candles) > 200:
            raise Blocked('invalid_page')
        pages += 1
        previous = None
        oldest = None
        for index, candle in enumerate(candles):
            if not isinstance(candle, dict):
                raise Blocked('invalid_candle')
            when = timestamp(candle.get('timestamp'))
            if when > timestamp(before) or (previous is not None and when >= previous):
                raise Blocked('nondecreasing_page_timestamps')
            if previous_oldest is not None and (when > previous_oldest or (when == previous_oldest and index != 0)):
                raise Blocked('invalid_page_boundary')
            previous = oldest = when
            row = normalize(candle, market, now)
            if row is None:
                excluded += 1
                continue
            day = row[0]
            if day in dates:
                if index != 0 or when != previous_oldest or dates[day] != row:
                    raise Blocked('conflicting_or_nonboundary_duplicate')
                duplicates += 1
            else:
                dates[day] = row
        if previous_oldest is not None and oldest is not None and oldest >= previous_oldest:
            raise Blocked('page_without_progress')
        if oldest is not None:
            previous_oldest = oldest
        if next_before is None:
            break
        next_time = timestamp(next_before)
        if not candles or next_time >= timestamp(before) or next_time > oldest:
            raise Blocked('cursor_without_progress')
        if next_before in cursors:
            raise Blocked('cursor_cycle')
        if oldest.astimezone(KST).date() < start:
            break
        before = next_before  # Preserve the provider cursor exactly.
    rows = [dates[day] for day in sorted(dates) if start.isoformat() <= day < cutoff.isoformat()]
    return rows, {'pages': pages, 'duplicate_boundaries': duplicates, 'incomplete_excluded': excluded,
                  'dedup_policy': 'identical first-row overlap with previous oldest only'}


def read_env(path):
    p = private_path(path)
    result = {}
    try:
        lines = p.read_text().splitlines()
        for line in lines:
            line = line.strip()
            if line.startswith('export '):
                line = line[7:].strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key, value = key.strip(), value.strip()
            if key not in ('TOSS_CLIENT_ID', 'TOSS_CLIENT_SECRET'):
                continue
            if key in result:
                raise Blocked('duplicate_credential')
            if value.startswith(('"', "'")):
                quote = value[0]
                end = value.find(quote, 1)
                if end < 0 or (value[end + 1:].strip() and not value[end + 1:].strip().startswith('#')):
                    raise Blocked('invalid_credential_syntax')
                value = value[1:end]
            else:
                value = re.split(r'\s+#', value, maxsplit=1)[0].strip()
            if not value or any(c in value for c in '\r\n\x00'):
                raise Blocked('empty_or_invalid_credential')
            result[key] = value
        if len(result) != 2:
            raise Blocked('missing_credential')
        return result
    except (OSError, UnicodeError):
        raise Blocked('credential_read_failed') from None


def iso_date(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise Blocked('invalid_date')
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise Blocked('invalid_date') from None


def validate_rows(rows, cutoff):
    if len(rows) <= 500:
        raise Blocked('insufficient_rows')
    days = [iso_date(row[0]) for row in rows]
    if any(a >= b for a, b in zip(days, days[1:])):
        raise Blocked('nonascending_dates')
    if sum(day <= BOUNDARY for day in days) < 2 or sum(day > BOUNDARY for day in days) < 2:
        raise Blocked('insufficient_is_oos')
    if days[-1] >= cutoff or (cutoff - days[-1]).days > 7:
        raise Blocked('stale_or_invalid_end')


def main(argv=None, *, send=transport, now=None, monotonic=time.monotonic, sleep=time.sleep):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--output', required=True, help='NEW private directory outside any git checkout')
    parser.add_argument('--universe-file', help='Public UniverseJSONv1 catalog; single-market acquisition batches allowed, native final snapshots require both markets')
    parser.add_argument('--start-date', default='2015-01-01')
    parser.add_argument('--cutoff-exclusive', required=True)
    parser.add_argument('--max-attempts', type=int, default=600)
    parser.add_argument('--max-minutes', type=float, default=30)
    parser.add_argument('--min-interval', type=float, default=.25)
    args = parser.parse_args(argv)
    output = None
    client = None
    entries = []
    current = None
    universe_raw = None
    now = now or dt.datetime.now(KST)
    try:
        if (not 1 <= args.max_attempts <= 600 or not math.isfinite(args.max_minutes)
                or not 0 < args.max_minutes <= 30 or not math.isfinite(args.min_interval)
                or not .25 <= args.min_interval <= 1800):
            raise Blocked('invalid_budget')
        start, cutoff = iso_date(args.start_date), iso_date(args.cutoff_exclusive)
        if start >= cutoff or cutoff > now.astimezone(KST).date():
            raise Blocked('invalid_date_range')
        instruments = [{'market': market, 'ticker': ticker,
                        'source_symbol': provider_symbol(market, ticker)}
                       for market, tickers in UNIVERSE.items() for ticker in tickers]
        if args.universe_file is not None:
            try:
                universe_raw = Path(args.universe_file).read_bytes()
                instruments = validate_universe(universe_raw)['instruments']
            except (OSError, ValueError, RecursionError):
                raise Blocked('invalid_universe') from None
        candidate = private_path(args.output, exists=False)
        if candidate.exists():
            raise Blocked('output_already_exists')
        # Parent must already exist and be private; never chmod unrelated ancestors.
        if not candidate.parent.is_dir():
            raise Blocked('output_parent_missing')
        token = private_path(args.token_file, exists=Path(args.token_file).exists())
        credentials = read_env(args.env_file)
        candidate.mkdir(mode=0o700)
        output = candidate
        if universe_raw is not None:
            immutable(output / 'universe.json', universe_raw)
        client = Client(output, args.max_attempts, args.max_minutes * 60, args.min_interval,
                        send, monotonic, sleep)
        lock = token.with_name(token.name + '.collection.lock')
        with file_lock(lock, client):
            auth = Auth(client, token, credentials)
            for instrument in instruments:
                market, ticker = instrument['market'], instrument['ticker']
                source_symbol = instrument['source_symbol']
                client.check()
                current = {'market': market, 'ticker': ticker}
                rows, quality = history(auth, market, ticker, start, cutoff, now,
                                        source_symbol=source_symbol)
                validate_rows(rows, cutoff)
                buffer = io.StringIO(newline='')
                writer = csv.writer(buffer, lineterminator='\n')
                writer.writerow(('date', 'open', 'high', 'low', 'close', 'volume'))
                writer.writerows(rows)
                raw = buffer.getvalue().encode()
                name = f'{market}_{ticker}.toss.csv'
                immutable(output / name, raw)
                entries.append(dict(current, source_symbol=source_symbol, currency='USD' if market == 'US' else 'KRW',
                                    session='US_REGULAR' if market == 'US' else 'KR_INTEGRATED',
                                    path=name, sha256=hashlib.sha256(raw).hexdigest(), rows=len(rows),
                                    first=rows[0][0], last=rows[-1][0], quality=quality,
                                    observed_history_start=rows[0][0],
                                    starts_after_requested_start=rows[0][0] > start.isoformat()))
            expected = {(item['market'], item['ticker']) for item in instruments}
            actual = {(e['market'], e['ticker']) for e in entries}
            if actual != expected or len(entries) != len(instruments):
                raise Blocked('incomplete_universe')
            if client.clock() >= client.deadline:
                raise Blocked('wall_budget_exhausted')
            manifest = {'schema_version': 2, 'provider': 'toss', 'adjusted': True, 'timezone': 'Asia/Seoul',
                        'cutoff_exclusive': cutoff.isoformat(), 'prepared_at': stamp(), 'status': 'complete',
                        'entries': entries, 'start_date': start.isoformat(), 'http_attempts': client.attempts,
                        'quality': {'exchange_calendar_guarantee': False,
                                    'calendar_limitation': 'No authoritative exchange calendar: holidays, missing interior sessions, historical suspensions and early closes are not certified. Weekday checks are not proof of completeness.',
                                    'completion_policy': 'US 20:15 America/New_York; KR integrated 20:15 Asia/Seoul; conservative post-extended-session delay, not provider finality guarantee; cutoff exclusive; DST-aware local-midnight daily stamps',
                                    'history_start_policy': 'Later observed starts accepted; not independently certified listing dates',
                                    'is_end': BOUNDARY.isoformat(), 'min_total_rows_exclusive': 500,
                                    'min_rows_each_side': 2, 'max_end_gap_calendar_days': 7},
                        'provenance': {'raw_directory': 'raw', 'request_log': 'requests.jsonl',
                                       'scope': 'oauth token issuance and daily candles only'}}
            if universe_raw is not None:
                manifest.update(schema_version=3, universe={
                    'path': 'universe.json', 'sha256': hashlib.sha256(universe_raw).hexdigest()})
            immutable(output / 'manifest.json', json_bytes(manifest))
        print(f'complete: {len(entries)} entries; private manifest.json written')
        return 0
    except (Exception, KeyboardInterrupt) as error:
        # No raw exception text, repr, traceback, provider body, or credential values.
        code = str(error) if isinstance(error, Blocked) else 'interrupted' if isinstance(error, KeyboardInterrupt) else 'internal_failure'
        if output is not None:
            failure = {'schema_version': 2, 'provider': 'toss', 'status': 'blocked', 'prepared_at': stamp(),
                       'errors': [dict(current or {}, code=code)], 'completed_entries': entries,
                       'http_attempts': client.attempts if client else 0}
            if universe_raw is not None:
                failure.update(schema_version=3, universe={
                    'path': 'universe.json', 'sha256': hashlib.sha256(universe_raw).hexdigest()})
            try:
                immutable(output / 'blocked.json', json_bytes(failure))
            except OSError:
                code = 'blocked_record_write_failed'
        print('blocked: ' + code)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
