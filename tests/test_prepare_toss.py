"""Issue #57 collector integration tests: synthetic transport, zero network."""
import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from test_universe_contract import catalog

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_toss57', ROOT / 'tools/prepare_toss.py')
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ExplicitCollector(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.env = self.root / 'synthetic.env'
        self.env.write_text('TOSS_CLIENT_ID=synthetic\nTOSS_CLIENT_SECRET=synthetic-secret\n')
        self.env.chmod(0o600)
        self.token = self.root / 'token.json'
        self.token.write_text(json.dumps({'access_token': 'synthetic-token', 'expires_at': 9999999999}))
        self.token.chmod(0o600)
        self.output = self.root / 'new-snapshot'
        self.catalog = catalog()
        self.catalog['instruments'] = [
            {'market': 'KR', 'ticker': '00AB12', 'source_symbol': 'ABC123', 'themes': ['synthetic']},
            {'market': 'US', 'ticker': 'BRK-B', 'source_symbol': 'BRK-B', 'themes': ['quality']}]
        # Public configuration is deliberately not a private credential file.
        self.universe = self.root / 'public-universe.json'
        self.raw = b' \n' + json.dumps(self.catalog, indent=3).encode() + b'\n'
        self.universe.write_bytes(self.raw)
        self.universe.chmod(0o644)
        self.calls = []
        self.clock = 0.0
        self.now = dt.datetime(2024, 2, 1, 14, tzinfo=m.KST)
        self.args = ['--env-file', str(self.env), '--token-file', str(self.token),
                     '--output', str(self.output), '--start-date', '2022-01-01',
                     '--cutoff-exclusive', '2024-02-01', '--universe-file', str(self.universe)]
        self.dates = [dt.date(2022, 1, 1) + dt.timedelta(days=i) for i in range(761)]

    def send(self, method, url, headers, body, timeout):
        self.calls.append(url)
        q = {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}
        markets = {item['source_symbol']: item['market'] for item in self.catalog['instruments']}
        market = markets[q['symbol']]
        zone = m.KST if market == 'KR' else m.ZoneInfo('America/New_York')
        before = m.timestamp(q['before'])
        eligible = [day for day in self.dates if dt.datetime.combine(day, dt.time(), zone) <= before]
        batch = eligible[-200:][::-1]
        candles = [{'timestamp': dt.datetime.combine(day, dt.time(), zone).isoformat(),
                    'currency': 'KRW' if market == 'KR' else 'USD', 'openPrice': 10,
                    'highPrice': 12, 'lowPrice': 9, 'closePrice': 11, 'volume': 0}
                   for day in batch]
        cursor = (dt.datetime.combine(batch[-1], dt.time(), zone) - dt.timedelta(seconds=1)).isoformat() if len(eligible) > 200 else None
        return 200, {}, json.dumps({'result': {'candles': candles, 'nextBefore': cursor}}).encode()

    def sleep(self, seconds):
        self.clock += seconds

    def run_collector(self, args=None, send=None):
        with contextlib.redirect_stdout(io.StringIO()) as text:
            try:
                result = m.main(args or self.args, send=send or self.send, now=self.now,
                                monotonic=lambda: self.clock, sleep=self.sleep)
            except SystemExit as error:
                self.fail(f'collector CLI rejected explicit universe: {error.code}')
        return result, text.getvalue()

    def test_invalid_catalog_preflight_has_no_side_effects_or_uncontrolled_error(self):
        original_token = self.token.read_bytes()
        self.universe.write_bytes(self.raw.replace(b'"point_in_time": false', b'"point_in_time": true'))
        result, text = self.run_collector()
        self.assertEqual(result, 1)
        self.assertEqual(text, 'blocked: invalid_universe\n')
        self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])
        self.assertEqual(self.token.read_bytes(), original_token)
        self.assertFalse(self.token.with_name('token.json.collection.lock').exists())

    def test_new_ipo_blocks_entire_snapshot_with_schema3_evidence_and_no_overwrite(self):
        # First configured identity succeeds; the second has only one valid row.
        original_send = self.send
        def short_history(method, url, headers, body, timeout):
            if parse_qs(urlparse(url).query)['symbol'] == ['BRK-B']:
                self.dates = [dt.date(2024, 1, 31)]
            return original_send(method, url, headers, body, timeout)
        result, text = self.run_collector(send=short_history)
        self.assertEqual(result, 1, text)
        self.assertFalse((self.output / 'manifest.json').exists())
        blocked = json.loads((self.output / 'blocked.json').read_bytes())
        self.assertEqual(blocked['schema_version'], 3)
        self.assertEqual(blocked['universe'], {'path': 'universe.json', 'sha256': hashlib.sha256(self.raw).hexdigest()})
        self.assertEqual(blocked['errors'], [{'market': 'US', 'ticker': 'BRK-B', 'code': 'insufficient_rows'}])
        self.assertEqual(len(blocked['completed_entries']), 1)
        self.assertEqual((self.output / 'universe.json').read_bytes(), self.raw)
        before = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        calls = len(self.calls)
        self.assertEqual(self.run_collector()[0], 1)
        self.assertEqual(len(self.calls), calls)
        self.assertEqual({str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}, before)

    def test_single_market_batch_is_collectable_but_not_a_native_final_universe(self):
        self.catalog['instruments'] = self.catalog['instruments'][:1]
        self.raw = json.dumps(self.catalog).encode()
        self.universe.write_bytes(self.raw)
        result, text = self.run_collector()
        self.assertEqual(result, 0, text)
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertEqual(len(manifest['entries']), 1)
        self.assertEqual(manifest['entries'][0]['ticker'], '00AB12')

    def test_explicit_mode_preserves_hard_cli_budgets_before_side_effects(self):
        for flag, values in {'--max-attempts': ['0', '601'], '--max-minutes': ['0', '30.001', 'nan'],
                             '--min-interval': ['0.249', '1801', 'nan']}.items():
            for value in values:
                with self.subTest(flag=flag, value=value):
                    result, text = self.run_collector(self.args + [flag, value])
                    self.assertEqual((result, text), (1, 'blocked: invalid_budget\n'))
                    self.assertFalse(self.output.exists())
                    self.assertFalse(self.calls)

    def test_explicit_mode_attempt_budget_still_counts_pagination_globally(self):
        result, text = self.run_collector(self.args + ['--max-attempts', '5'])
        self.assertEqual(result, 1, text)
        blocked = json.loads((self.output / 'blocked.json').read_bytes())
        self.assertEqual(blocked['http_attempts'], 5)
        self.assertEqual(blocked['errors'][0]['code'], 'attempt_budget_exhausted')
        self.assertEqual(len(blocked['completed_entries']), 1)
        self.assertFalse((self.output / 'manifest.json').exists())
        starts = [json.loads(line) for line in (self.output / 'requests.jsonl').read_text().splitlines()
                  if json.loads(line)['event'] == 'start']
        self.assertEqual(len(starts), 5)
        self.assertTrue(all(r['endpoint'] == '/api/v1/candles' for r in starts))
        self.assertGreaterEqual(self.clock, 1.0)

    def test_unavailable_symbol_blocks_instead_of_silently_omitting_it(self):
        def unavailable(*args):
            self.calls.append(args[1])
            return 404, {}, b'provider-secret-symbol-not-found'
        result, text = self.run_collector(send=unavailable)
        self.assertEqual((result, text), (1, 'blocked: http_404\n'))
        self.assertFalse((self.output / 'manifest.json').exists())
        blocked = json.loads((self.output / 'blocked.json').read_bytes())
        self.assertEqual(blocked['completed_entries'], [])
        self.assertEqual(blocked['errors'], [{'market': 'KR', 'ticker': '00AB12', 'code': 'http_404'}])
        self.assertNotIn('provider-secret', (self.output / 'blocked.json').read_text())

    def test_existing_row_split_and_ohlc_guards_apply_to_explicit_catalog(self):
        all_dates = self.dates
        for name, dates, bad_price, code in [
            ('short', all_dates[-10:], False, 'insufficient_rows'),
            ('no_is', [dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(700)], False, 'insufficient_is_oos'),
            ('no_oos', [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(700)], False, 'insufficient_is_oos'),
            ('stale', all_dates[:-20], False, 'stale_or_invalid_end'),
            ('ohlc', all_dates, True, 'invalid_ohlcv'),
        ]:
            with self.subTest(name=name):
                self.dates = dates
                self.output = self.root / name
                args = self.args.copy()
                args[args.index('--output') + 1] = str(self.output)
                if name == 'no_oos':
                    args[args.index('--start-date') + 1] = '2020-01-01'
                self.now = dt.datetime(2024, 2, 1, 14, tzinfo=m.KST)
                if name == 'no_is':
                    self.now = dt.datetime(2025, 2, 1, 14, tzinfo=m.KST)
                    args[args.index('--cutoff-exclusive') + 1] = '2025-02-01'
                def send(*params):
                    status, headers, raw = self.send(*params)
                    if bad_price:
                        raw = raw.replace(b'"openPrice": 10', b'"openPrice": -1')
                    return status, headers, raw
                result, text = self.run_collector(args, send)
                self.assertEqual((result, text), (1, f'blocked: {code}\n'))
                self.assertFalse((self.output / 'manifest.json').exists())
                blocked = json.loads((self.output / 'blocked.json').read_bytes())
                self.assertEqual(blocked['errors'][0]['code'], code)
                self.assertEqual((self.output / 'universe.json').read_bytes(), self.raw)

    def test_explicit_catalog_exact_selection_aliases_raw_bytes_and_schema3(self):
        result, text = self.run_collector()
        self.assertEqual(result, 0, text)
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertEqual(manifest['schema_version'], 3)
        self.assertEqual(manifest['universe'], {'path': 'universe.json', 'sha256': hashlib.sha256(self.raw).hexdigest()})
        self.assertEqual((self.output / 'universe.json').read_bytes(), self.raw)
        self.assertEqual((self.output / 'universe.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual([(e['market'], e['ticker'], e['source_symbol']) for e in manifest['entries']],
                         [('KR', '00AB12', 'ABC123'), ('US', 'BRK-B', 'BRK-B')])
        self.assertEqual({parse_qs(urlparse(url).query)['symbol'][0] for url in self.calls}, {'ABC123', 'BRK-B'})
        for entry in manifest['entries']:
            self.assertEqual(entry['currency'], 'KRW' if entry['market'] == 'KR' else 'USD')
            self.assertEqual(entry['session'], 'KR_INTEGRATED' if entry['market'] == 'KR' else 'US_REGULAR')
            raw = (self.output / entry['path']).read_bytes()
            self.assertEqual(entry['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertGreater(entry['rows'], 500)
        self.assertIn('complete: 2 entries', text)
