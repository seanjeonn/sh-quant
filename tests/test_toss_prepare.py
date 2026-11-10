"""OFFLINE SYNTHETIC fixtures only; never market research artifacts."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_toss', ROOT / 'tools/prepare_toss.py')
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CompletionAndRetryRegression(unittest.TestCase):
    def test_us_volume_waits_until_extended_session_and_delay_finish(self):
        import datetime as dt
        from zoneinfo import ZoneInfo
        candle = {'timestamp': '2026-11-09T14:00:00+09:00', 'openPrice': 10,
                  'highPrice': 12, 'lowPrice': 9, 'closePrice': 11, 'volume': 0, 'currency': 'USD'}
        # Synthetic candle: 17:00 New York is after regular close but not complete.
        self.assertIsNone(m.normalize(candle, 'US', dt.datetime(2026,11,9,17,0,tzinfo=ZoneInfo('America/New_York'))))
        self.assertIsNotNone(m.normalize(candle, 'US', dt.datetime(2026,11,9,20,15,tzinfo=ZoneInfo('America/New_York'))))
        summer = dict(candle, timestamp='2026-07-06T13:00:00+09:00')
        self.assertIsNone(m.normalize(summer, 'US', dt.datetime(2026,7,6,20,14,tzinfo=ZoneInfo('America/New_York'))))
        self.assertIsNotNone(m.normalize(summer, 'US', dt.datetime(2026,7,6,20,15,tzinfo=ZoneInfo('America/New_York'))))

    def test_503_respects_retry_after_and_remaining_budget(self):
        with tempfile.TemporaryDirectory() as td:
            clock = Clock()
            replies = [(503, {'Retry-After':'120'}, b'synthetic'), (200, {}, b'{}')]
            client = m.Client(Path(td).resolve(), 3, 200, .25,
                              lambda *args: replies.pop(0), clock.monotonic, clock.sleep)
            self.assertEqual(client.request('/api/v1/candles'), {})
            self.assertGreaterEqual(clock.t, 120)
        with tempfile.TemporaryDirectory() as td:
            clock = Clock()
            client = m.Client(Path(td).resolve(), 3, 100, .25,
                              lambda *args: (503, {'Retry-After':'120'}, b'synthetic'), clock.monotonic, clock.sleep)
            with self.assertRaises(m.Blocked):
                client.request('/api/v1/candles')
            self.assertEqual(client.attempts, 1)


class SymbolMapping(unittest.TestCase):
    def test_explicit_provider_alias_preserves_research_identity(self):
        self.assertTrue(hasattr(m, 'provider_symbol'), 'explicit provider symbol mapping missing')
        self.assertEqual(m.provider_symbol('US', 'BRK-B'), 'BRK.B')
        self.assertEqual(m.provider_symbol('US', 'SPY'), 'SPY')
        self.assertEqual(m.provider_symbol('KR', '005930'), '005930')
        self.assertIn('BRK-B', m.UNIVERSE['US'])
        self.assertNotIn('BRK.B', m.UNIVERSE['US'])


class Credentials(unittest.TestCase):
    def test_safe_env_and_private_paths(self):
        self.assertTrue(hasattr(m, 'read_env'), 'collector credential reader missing')
        with tempfile.TemporaryDirectory() as td:
            p = Path(td).resolve() / 'keys.env'
            p.write_text("export TOSS_CLIENT_ID='synthetic+id'\nTOSS_CLIENT_SECRET=synthetic\nIGNORED=$(false)\n")
            p.chmod(0o600)
            self.assertEqual(m.read_env(p)['TOSS_CLIENT_ID'], 'synthetic+id')
            for text in ['TOSS_CLIENT_ID=x\nTOSS_CLIENT_ID=y\nTOSS_CLIENT_SECRET=z', 'TOSS_CLIENT_ID=\nTOSS_CLIENT_SECRET=z']:
                p.write_text(text)
                with self.assertRaises(m.Blocked):
                    m.read_env(p)
            p.chmod(0o644)
            with self.assertRaises(m.Blocked):
                m.read_env(p)
            p.chmod(0o600)
            link = Path(td) / 'link'
            link.symlink_to(p)
            with self.assertRaises(m.Blocked):
                m.read_env(link)
            with self.assertRaises(m.Blocked):
                m.private_path(ROOT / 'synthetic-private', exists=False)


class Clock:
    def __init__(self):
        self.t = 0.0
    def monotonic(self):
        return self.t
    def sleep(self, seconds):
        self.t += seconds


class HTTP(unittest.TestCase):
    def test_retry_gzip_raw_budget_and_redaction(self):
        self.assertTrue(hasattr(m, 'Client'), 'bounded HTTP client missing')
        import gzip
        import json
        with tempfile.TemporaryDirectory() as td:
            out = Path(td).resolve()
            clock = Clock()
            seen = []
            replies = [(500, {}, b'synthetic-secret'), (429, {'Retry-After': '2'}, b'busy'),
                       (200, {'Content-Encoding': 'gzip'}, gzip.compress(b'{"result":{}}'))]
            def transport(method, url, headers, body, timeout):
                seen.append(url)
                return replies.pop(0)
            client = m.Client(out, 5, 10, .25, transport, clock.monotonic, clock.sleep)
            value = client.request('/api/v1/candles', {'before': '2020-01-01T00:00:00+09:00'}, token='synthetic-token')
            self.assertEqual(value, {'result': {}})
            self.assertEqual(client.attempts, 3)
            self.assertIn('%2B09%3A00', seen[0])
            raw = sorted((out / 'raw').glob('*.bin'))
            self.assertEqual(len(raw), 3)
            self.assertEqual(raw[0].read_bytes(), b'synthetic-secret')
            audit = (out / 'requests.jsonl').read_text()
            self.assertNotIn('synthetic-secret', audit)
            self.assertNotIn('synthetic-token', audit)
            self.assertEqual(len([json.loads(x) for x in audit.splitlines()]), 6)
            with self.assertRaises(m.Blocked):
                client.request('/api/v1/orders')
            client.max_attempts = 3
            with self.assertRaises(m.Blocked):
                client.request('/api/v1/candles')
            self.assertEqual(len(raw), 3)

    def test_network_retry_date_retry_after_and_wall_clock(self):
        import email.utils
        import datetime
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            clock = Clock()
            responses = [OSError('synthetic-secret'), (429, {'Retry-After': email.utils.format_datetime(datetime.datetime.fromtimestamp(104, datetime.timezone.utc))}, b'secret'), (200, {}, b'{}')]
            def send(*args):
                reply = responses.pop(0)
                if isinstance(reply, Exception):
                    raise reply
                return reply
            client = m.Client(Path(td).resolve(), 5, 10, 0, send, clock.monotonic, clock.sleep)
            with patch.object(m.time, 'time', return_value=100):
                self.assertEqual(client.request('/api/v1/candles'), {})
            self.assertEqual(client.attempts, 3)
            self.assertEqual(len(list((Path(td) / 'raw').glob('*'))), 3)
            self.assertGreaterEqual(clock.t, 5)

    def test_dribbling_transport_cannot_exceed_wall_budget(self):
        import time
        with tempfile.TemporaryDirectory() as td:
            def slow(*args):
                time.sleep(.3)
                return 200, {}, b'{}'
            client = m.Client(Path(td).resolve(), 5, .04, 0, slow)
            started = time.monotonic()
            with self.assertRaises(m.Blocked):
                client.request('/api/v1/candles')
            self.assertLess(time.monotonic() - started, .2)
            self.assertEqual(len(list((Path(td) / 'raw').glob('*'))), 1)

    def test_interruption_still_persists_attempt_end(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            def interrupted(*args):
                raise KeyboardInterrupt()
            client = m.Client(Path(td).resolve(), 5, 10, 0, interrupted)
            with self.assertRaises(m.Blocked):
                client.request('/api/v1/candles')
            events = [json.loads(line)['event'] for line in (Path(td) / 'requests.jsonl').read_text().splitlines()]
            self.assertEqual(events, ['start', 'end'])
            self.assertEqual(len(list((Path(td) / 'raw').glob('*'))), 1)

    def test_fatal_403_and_wall_budget(self):
        self.assertTrue(hasattr(m, 'Client'), 'bounded HTTP client missing')
        for status, headers in [(403, {}), (429, {'Retry-After': '999999'})]:
            with tempfile.TemporaryDirectory() as td:
                clock = Clock()
                client = m.Client(Path(td).resolve(), 10, 2, 0,
                                  lambda *a: (status, headers, b'secret'), clock.monotonic, clock.sleep)
                with self.assertRaises(m.Blocked):
                    client.request('/api/v1/candles')
                self.assertEqual(client.attempts, 1)
                self.assertLessEqual(clock.t, 2)


def candle(date='2020-01-02', market='US', **changes):
    value = {'timestamp': date + ('T14:00:00+09:00' if market == 'US' else 'T00:00:00+09:00'),
             'openPrice': '10', 'highPrice': '12', 'lowPrice': '9', 'closePrice': '11',
             'volume': '0', 'currency': 'USD' if market == 'US' else 'KRW'}
    value.update(changes)
    return value


class Quality(unittest.TestCase):
    def test_daily_dates_dst_zero_volume_and_invalid(self):
        self.assertTrue(hasattr(m, 'normalize'), 'strict bar normalizer missing')
        now = m.dt.datetime(2026, 11, 10, 14, tzinfo=m.KST)
        for timestamp in ['2024-01-03T14:00:00+09:00', '2024-07-03T13:00:00+09:00']:
            row = m.normalize(candle(timestamp=timestamp), 'US', now)
            self.assertEqual(row[0], timestamp[:10])
            self.assertEqual(row[-1], 0)
        for changes in [{'openPrice': None}, {'closePrice': 'NaN'}, {'highPrice': '8'},
                        {'volume': '-1'}, {'currency': 'KRW'}, {'timestamp': '2024-01-03T00:00:00'},
                        {'timestamp': '2024-01-03T00:00:00+09:00'}]:
            with self.subTest(changes=changes), self.assertRaises(m.Blocked):
                m.normalize(candle(**changes), 'US', now)
        self.assertIsNone(m.normalize(candle('2026-11-10', 'KR'), 'KR', now))
        self.assertIsNotNone(m.normalize(candle('2026-11-09', 'US'), 'US', now))

    def test_quality_thresholds_universe_and_immutability(self):
        import re
        source = (ROOT / 'src/data.rs').read_text()
        for market in ('US', 'KR'):
            group = re.search(r'"' + market + r'"\s*=>\s*&\[(.*?)\]', source, re.S).group(1)
            self.assertEqual(tuple(re.findall(r'"([A-Z0-9-]+)"', group)), m.UNIVERSE[market])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'synthetic.bin'
            m.immutable(path, b'first')
            with self.assertRaises(FileExistsError):
                m.immutable(path, b'second')
            self.assertEqual(path.read_bytes(), b'first')
        for rows in [[], [('2024-01-01', 1, 1, 1, 1, 0)] * 501,
                     [(str(m.dt.date(2020, 1, 1) + m.dt.timedelta(days=i)), 1, 1, 1, 1, 0) for i in range(501)]]:
            with self.assertRaises(m.Blocked):
                m.validate_rows(rows, m.dt.date(2026, 11, 10))

    def test_pagination_exact_cursor_boundary_dedup_cycle(self):
        self.assertTrue(hasattr(m, 'history'), 'paginated history missing')
        now = m.dt.datetime(2026, 11, 10, 14, tzinfo=m.KST)
        pages = [{'result': {'candles': [candle('2020-01-03'), candle('2020-01-02')],
                            'nextBefore': '2020-01-02T14:00:00+09:00'}},
                 {'result': {'candles': [candle('2020-01-02'), candle('2020-01-01')], 'nextBefore': None}}]
        class Fake:
            def __init__(self): self.params = []
            def candles(self, params):
                self.params.append(params.copy())
                return pages.pop(0)
        fake = Fake()
        rows, info = m.history(fake, 'US', 'SPY', m.dt.date(2015, 1, 1), m.dt.date(2026, 11, 10), now)
        self.assertEqual([r[0] for r in rows], ['2020-01-01', '2020-01-02', '2020-01-03'])
        self.assertEqual(info['duplicate_boundaries'], 1)
        self.assertEqual(fake.params[1]['before'], '2020-01-02T14:00:00+09:00')
        pages[:] = [{'result': {'candles': [candle()], 'nextBefore': '2020-01-02T14:00:00+09:00'}}] * 2
        with self.assertRaises(m.Blocked):
            m.history(Fake(), 'US', 'SPY', m.dt.date(2015, 1, 1), m.dt.date(2026, 11, 10), now)


class Authentication(unittest.TestCase):
    def test_token_reuse_refresh_once_and_locks(self):
        self.assertTrue(hasattr(m, 'Auth'), 'locked reusable authentication missing')
        import json
        import fcntl
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            token = root / 'token.json'
            token.write_text(json.dumps({'access_token': 'synthetic-existing', 'expires_at': m.time.time() + 86400}))
            token.chmod(0o600)
            clock = Clock()
            calls = []
            responses = [(200, {}, b'{"result":{}}'), (401, {}, b'secret'),
                         (200, {}, b'{"access_token":"synthetic-new","expires_in":86400}'),
                         (200, {}, b'{"result":{}}'), (401, {}, b'bad')]
            def send(method, url, headers, body, timeout):
                calls.append(url)
                return responses.pop(0)
            out = root / 'out'
            out.mkdir(mode=0o700)
            client = m.Client(out, 20, 50, 0, send, clock.monotonic, clock.sleep)
            auth = m.Auth(client, token, {'TOSS_CLIENT_ID': 'synthetic+id', 'TOSS_CLIENT_SECRET': 'synthetic-secret'})
            auth.candles({})
            self.assertEqual(len(calls), 1)
            auth.candles({})
            self.assertEqual(sum('/oauth2/token' in url for url in calls), 1)
            self.assertEqual(json.loads(token.read_text())['access_token'], 'synthetic-new')
            with self.assertRaises(m.Blocked):
                auth.candles({})
            self.assertEqual(len(list((out / 'raw').glob('*.bin'))), 4)
            self.assertNotIn('synthetic-new', (out / 'requests.jsonl').read_text())
            with m.file_lock(root / 'test.lock', client):
                with open(root / 'test.lock', 'rb') as f:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


class EndToEnd(unittest.TestCase):
    def test_full_synthetic_universe_manifest_and_no_overwrite(self):
        self.assertTrue(hasattr(m, 'main'), 'runnable collector missing')
        import json
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            env = root / 'keys.env'
            env.write_text('TOSS_CLIENT_ID=synthetic\nTOSS_CLIENT_SECRET=synthetic-secret\n')
            env.chmod(0o600)
            token = root / 'token.json'
            token.write_text(json.dumps({'access_token': 'synthetic-token', 'expires_at': m.time.time() + 86400}))
            token.chmod(0o600)
            output = root / 'dataset'
            clock = Clock()
            now = m.dt.datetime(2026, 11, 10, 14, tzinfo=m.KST)
            dates = []
            day = m.dt.date(2019, 1, 1)
            while day < now.date():
                if day.weekday() < 5:
                    dates.append(day)
                day += m.dt.timedelta(days=1)
            def send(method, url, headers, body, timeout):
                from urllib.parse import urlparse, parse_qs
                q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
                self.assertEqual(q['adjusted'], 'true')
                self.assertEqual(q['count'], '200')
                market = 'KR' if q['symbol'].isdigit() else 'US'
                zone = m.ZoneInfo('America/New_York') if market == 'US' else m.KST
                before = m.timestamp(q['before'])
                eligible = [d for d in dates if m.dt.datetime.combine(d, m.dt.time(), zone) <= before]
                batch = eligible[-200:][::-1]
                values = [candle(d.isoformat(), market, timestamp=m.dt.datetime.combine(d, m.dt.time(), zone).astimezone(m.KST).isoformat()) for d in batch]
                next_before = (m.dt.datetime.combine(batch[-1], m.dt.time(), zone) - m.dt.timedelta(seconds=1)).isoformat() if len(eligible) > 200 else None
                return 200, {}, json.dumps({'result': {'candles': values, 'nextBefore': next_before}}).encode()
            args = ['--env-file', str(env), '--token-file', str(token), '--output', str(output),
                    '--start-date', '2015-01-01', '--cutoff-exclusive', '2026-11-10']
            self.assertEqual(m.main(args, send=send, now=now, monotonic=clock.monotonic, sleep=clock.sleep), 0)
            manifest = json.loads((output / 'manifest.json').read_text())
            self.assertEqual(manifest['schema_version'], 2)
            self.assertEqual(manifest['status'], 'complete')
            self.assertEqual(len(manifest['entries']), 24)
            self.assertEqual(manifest['provider'], 'toss')
            self.assertEqual(manifest['timezone'], 'Asia/Seoul')
            for entry in manifest['entries']:
                raw = (output / entry['path']).read_bytes()
                self.assertEqual(entry['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(entry['rows'], len(dates))
                self.assertEqual((output / entry['path']).stat().st_mode & 0o777, 0o600)
            self.assertNotIn('synthetic-token', (output / 'manifest.json').read_text())
            self.assertEqual(m.main(args, send=send, now=now), 1)

    def test_quality_block_persisted_without_complete_manifest(self):
        self.assertTrue(hasattr(m, 'main'), 'runnable collector missing')
        import json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            env = root / 'keys.env'
            env.write_text('TOSS_CLIENT_ID=synthetic\nTOSS_CLIENT_SECRET=synthetic-secret\n')
            env.chmod(0o600)
            token = root / 'token.json'
            token.write_text(json.dumps({'access_token': 'synthetic-token', 'expires_at': m.time.time() + 86400}))
            token.chmod(0o600)
            output = root / 'blocked'
            args = ['--env-file', str(env), '--token-file', str(token), '--output', str(output), '--cutoff-exclusive', '2026-11-10']
            send = lambda *a: (200, {}, json.dumps({'result': {'candles': [candle(openPrice=None)], 'nextBefore': None}}).encode())
            self.assertEqual(m.main(args, send=send, now=m.dt.datetime(2026, 11, 10, 14, tzinfo=m.KST)), 1)
            self.assertFalse((output / 'manifest.json').exists())
            blocked = json.loads((output / 'blocked.json').read_text())
            self.assertEqual(blocked['status'], 'blocked')
            self.assertEqual(blocked['errors'][0]['code'], 'invalid_ohlcv')
            self.assertEqual(len(list((output / 'raw').glob('*.bin'))), 1)


if __name__ == '__main__':
    unittest.main()
