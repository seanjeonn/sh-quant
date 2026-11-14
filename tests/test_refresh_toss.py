"""#61: vertical TDD, synthetic private snapshots and HTTP transport only."""
import contextlib
import csv
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from test_prepare_toss import m as legacy
from test_universe_contract import catalog

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/refresh_toss.py'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_refresh():
    if not SOURCE.exists():
        return None
    spec = importlib.util.spec_from_file_location('refresh61', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.m = load_refresh()
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.env = self.root / 'synthetic.env'
        self.write(self.env, b'TOSS_CLIENT_ID=synthetic\nTOSS_CLIENT_SECRET=synthetic-secret\n')
        self.token = self.root / 'token.json'
        self.write(self.token, json.dumps(dict(access_token='synthetic-token', expires_at=9999999999)).encode())
        self.universe = self.root / 'catalog.json'
        self.catalog = catalog()
        self.catalog['instruments'] = [
            dict(market='KR', ticker='00AB12', source_symbol='ABC123', themes=['synthetic']),
            dict(market='US', ticker='BRK-B', source_symbol='BRK.B', themes=['quality'])]
        self.catalog_raw = b' \n' + json.dumps(self.catalog, indent=3).encode() + b'\n'
        self.write(self.universe, self.catalog_raw)
        self.universe.chmod(0o644)
        self.base = self.root / 'seed'
        self.output = self.root / 'new'
        self.now = dt.datetime(2024, 2, 1, 14, tzinfo=legacy.KST)
        self.clock = 0.
        self.calls = []
        self.dates = [dt.date(2022, 1, 1) + dt.timedelta(days=i) for i in range(761)]
        seed_args = ['--env-file', str(self.env), '--token-file', str(self.token), '--output', str(self.base),
                     '--universe-file', str(self.universe), '--start-date', '2022-01-01', '--cutoff-exclusive', '2024-01-31']
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(legacy.main(seed_args, send=self.send, now=self.now,
                                         monotonic=lambda: self.clock, sleep=self.sleep), 0)
        self.manifest_path = self.base / 'manifest.json'
        self.manifest = json.loads(self.manifest_path.read_bytes())
        self.manifest['prepared_at'] = '2024-01-31T14:00:00+09:00'
        self.save_base()
        self.calls.clear()
        self.clock = 0.
        self.args = ['--env-file', str(self.env), '--token-file', str(self.token), '--output', str(self.output),
                     '--universe-file', str(self.universe), '--universe-sha256', sha(self.catalog_raw),
                     '--base-manifest', str(self.manifest_path), '--base-sha256', sha(self.manifest_path.read_bytes()),
                     '--start-date', '2022-01-01', '--cutoff-exclusive', '2024-02-01']

    def write(self, path, raw):
        path.write_bytes(raw)
        path.chmod(0o600)

    def save_base(self):
        self.write(self.manifest_path, json.dumps(self.manifest).encode())
        if hasattr(self, 'args'):
            self.args[self.args.index('--base-sha256') + 1] = sha(self.manifest_path.read_bytes())

    def send(self, method, url, headers, body, timeout):
        self.calls.append(url)
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        market = next(i['market'] for i in self.catalog['instruments'] if i['source_symbol'] == q['symbol'])
        zone = legacy.KST if market == 'KR' else legacy.ZoneInfo('America/New_York')
        before = legacy.timestamp(q['before'])
        eligible = [d for d in self.dates if dt.datetime.combine(d, dt.time(), zone) <= before]
        batch = eligible[-200:][::-1]
        candles = [dict(timestamp=dt.datetime.combine(d, dt.time(), zone).isoformat(),
                        currency='KRW' if market == 'KR' else 'USD', openPrice=10,
                        highPrice=12, lowPrice=9, closePrice=11, volume=0) for d in batch]
        cursor = (dt.datetime.combine(batch[-1], dt.time(), zone) - dt.timedelta(seconds=1)).isoformat() if len(eligible) > 200 else None
        return 200, {}, json.dumps(dict(result=dict(candles=candles, nextBefore=cursor))).encode()

    def sleep(self, seconds):
        self.clock += seconds

    def run_refresh(self, args=None, send=None):
        self.assertIsNotNone(self.m, 'refresh CLI implementation is missing')
        with contextlib.redirect_stdout(io.StringIO()) as text:
            result = self.m.main(args or self.args, send=send or self.send, now=self.now,
                                 monotonic=lambda: self.clock, sleep=self.sleep)
        return result, text.getvalue()

    def test_exact_overlap_appends_using_one_page_per_symbol_and_keeps_base(self):
        before = {str(f.relative_to(self.base)): f.read_bytes() for f in self.base.rglob('*') if f.is_file()}
        result, text = self.run_refresh()
        self.assertEqual(result, 0, text)
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(manifest['http_attempts'], 2)
        self.assertEqual(manifest['schema_version'], 3)
        self.assertEqual((self.output / 'universe.json').read_bytes(), self.catalog_raw)
        refresh = manifest['provenance']['refresh']
        self.assertEqual(refresh['policy'], 'overlap200_prefix_carried_v1')
        self.assertEqual(refresh['base_manifest_sha256'], sha(before['manifest.json']))
        self.assertEqual([s['mode'] for s in refresh['symbols']], ['append', 'append'])
        self.assertIn('outside', refresh['revision_limitation'])
        self.assertIn('vintage', refresh['prefix_vintage'])
        for entry in manifest['entries']:
            self.assertEqual(entry['rows'], 761)
            self.assertEqual(entry['last'], '2024-01-31')
            rows = list(csv.reader(io.StringIO((self.output / entry['path']).read_text())))
            old = next(e for e in self.manifest['entries'] if e['ticker'] == entry['ticker'])
            self.assertEqual(rows[:-1], list(csv.reader(io.StringIO((self.base / old['path']).read_text()))))
        self.assertEqual(before, {str(f.relative_to(self.base)): f.read_bytes() for f in self.base.rglob('*') if f.is_file()})

    def test_schema3_base_metadata_is_validated_before_http(self):
        original = json.loads(json.dumps(self.manifest))
        mutations = [
            lambda b: b.update(schema_version=True), lambda b: b.update(schema_version=2),
            lambda b: b.update(provider='other'), lambda b: b.update(status='blocked'),
            lambda b: b.update(adjusted=1), lambda b: b.update(timezone='UTC'),
            lambda b: b.update(start_date='2022-01-02'), lambda b: b.update(cutoff_exclusive='2024-02-01'),
            lambda b: b.update(prepared_at='2025-01-01T00:00:00+09:00'),
            lambda b: b['entries'].pop(), lambda b: b['entries'].append(b['entries'][0]),
            lambda b: b['entries'][0].update(source_symbol='WRONG'),
            lambda b: b['entries'][0].update(currency='USD'),
            lambda b: b['entries'][0].update(session='US_REGULAR'),
            lambda b: b['entries'][0].update(rows=True),
            lambda b: b['entries'][0].update(first='2022-01-02'),
            lambda b: b['entries'][0].update(observed_history_start='2000-01-01'),
            lambda b: b['entries'][0].update(starts_after_requested_start=1),
            lambda b: b['entries'][0].update(quality={}),
            lambda b: b['quality'].update(exchange_calendar_guarantee=True),
            lambda b: b['quality'].update(min_rows_each_side=1),
            lambda b: b['universe'].update(sha256='0' * 64),
        ]
        for change in mutations:
            with self.subTest(change=mutations.index(change)):
                self.manifest = json.loads(json.dumps(original))
                change(self.manifest)
                self.save_base()
                result, text = self.run_refresh()
                self.assertEqual((result, text), (1, 'blocked: invalid_base_metadata\n'))
                self.assertFalse(self.calls)
                self.assertFalse(self.output.exists())

    def test_base_csv_bytes_dates_and_ohlcv_are_checked_before_http(self):
        entry = self.manifest['entries'][0]
        path = self.base / entry['path']
        original = path.read_bytes()
        cases = [
            (original + b' ', False),
            (original.replace(b'date,open,high,low,close,volume', b'date,high,open,low,close,volume'), True),
            (original.replace(b'10.0', b'nan', 1), True),
            (original.replace(b'10.0', b'-1.0', 1), True),
            (original.replace(b'12.0', b'8.0', 1), True),
            (original.replace(b'0.0\n', b'-1.0\n', 1), True),
            (original.replace(b'2022-01-01', b'2021-12-31', 1), True),
            (original.replace(b'2022-01-02', b'2022-01-01', 1), True),
            (original.replace(b'2022-01-01,10.0', b'2022-01-01', 1), True),
            (original.replace(b'2022-01-01', b'2022-1-01', 1), True),
        ]
        for index, (raw, rehash) in enumerate(cases):
            with self.subTest(index=index):
                self.write(path, raw)
                entry['sha256'] = sha(raw) if rehash else sha(original)
                self.save_base()
                result, text = self.run_refresh()
                self.assertEqual((result, text), (1, 'blocked: invalid_base_csv\n'))
                self.assertFalse(self.calls)
                self.assertFalse(self.output.exists())

    def test_private_csv_paths_and_file_aliases_are_rejected_before_http(self):
        entry = self.manifest['entries'][0]
        original = entry['path']
        for bad in ('../outside.csv', str(self.base / original), './' + original,
                    'nested//file.csv', 'raw/../' + original, 'universe.json'):
            with self.subTest(path=bad):
                entry['path'] = bad
                self.save_base()
                result, text = self.run_refresh()
                self.assertEqual((result, text), (1, 'blocked: unsafe_base_path\n'))
                self.assertFalse(self.calls)
                self.assertFalse(self.output.exists())
        entry['path'] = original
        path = self.base / original
        backup = self.root / 'alias.csv'
        os.link(path, backup)
        self.save_base()
        result, text = self.run_refresh()
        self.assertEqual((result, text), (1, 'blocked: unsafe_file_permissions\n'))
        self.assertFalse(self.calls)
        self.assertFalse(self.output.exists())

    def test_overlap_revision_refetches_entire_symbol_without_rescaling(self):
        def revised(*args):
            status, headers, raw = self.send(*args)
            if parse_qs(urlparse(args[1]).query)['symbol'] == ['ABC123']:
                raw = raw.replace(b'"closePrice": 11', b'"closePrice": 10.5')
            return status, headers, raw
        result, text = self.run_refresh(send=revised)
        self.assertEqual(result, 0, text)
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertEqual(len(self.calls), 6)
        self.assertEqual(manifest['http_attempts'], 6)
        self.assertEqual([s['mode'] for s in manifest['provenance']['refresh']['symbols']], ['full-refresh', 'append'])
        rows = list(csv.reader(io.StringIO((self.output / manifest['entries'][0]['path']).read_text())))[1:]
        self.assertTrue(all(float(row[4]) == 10.5 for row in rows))
        self.assertEqual(float(list(csv.reader(io.StringIO((self.base / self.manifest['entries'][0]['path']).read_text())))[1][4]), 11.)

    def test_a_newly_reported_interior_date_requires_full_refresh(self):
        entry = self.manifest['entries'][0]
        path = self.base / entry['path']
        raw = path.read_bytes()
        lines = raw.splitlines(keepends=True)
        del lines[-30]
        changed = b''.join(lines)
        self.write(path, changed)
        entry.update(sha256=sha(changed), rows=entry['rows'] - 1)
        self.save_base()
        result, text = self.run_refresh()
        self.assertEqual(result, 0, text)
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertEqual(manifest['provenance']['refresh']['symbols'][0]['mode'], 'full-refresh')
        self.assertEqual(manifest['entries'][0]['rows'], 761)
        self.assertEqual(len(self.calls), 6)

    def test_cli_budget_caps_are_preflight_and_finite(self):
        for flag, values in {'--max-attempts': ['0', '601'], '--max-minutes': ['0', '20.001', 'nan', 'inf'],
                             '--min-interval': ['0.249', 'nan', 'inf']}.items():
            for value in values:
                with self.subTest(flag=flag, value=value):
                    result, text = self.run_refresh(self.args + [flag, value])
                    self.assertEqual((result, text), (1, 'blocked: invalid_budget\n'))
                    self.assertFalse(self.calls)
                    self.assertFalse(self.output.exists())

    def test_base_changed_during_http_blocks_before_fallback_or_publication(self):
        def changed(*args):
            response = self.send(*args)
            path = self.base / self.manifest['entries'][0]['path']
            self.write(path, path.read_bytes().replace(b'10.0', b'10.1', 1))
            return response
        result, text = self.run_refresh(send=changed)
        self.assertEqual((result, text), (1, 'blocked: base_changed\n'))
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.output / 'manifest.json').exists())
        blocked = json.loads((self.output / 'blocked.json').read_bytes())
        self.assertEqual(blocked['errors'][0]['code'], 'base_changed')
        self.assertTrue(list((self.output / 'raw').iterdir()))

    def test_weekend_unchanged_preserves_exact_prefix_and_can_be_the_next_base(self):
        for entry in self.manifest['entries']:
            path = self.base / entry['path']
            raw = path.read_bytes().replace(b'10.0', b'10.000')
            self.write(path, raw)
            entry['sha256'] = sha(raw)
        self.save_base()
        self.dates = self.dates[:-1]
        result, text = self.run_refresh()
        self.assertEqual(result, 0, text)
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertEqual([s['mode'] for s in manifest['provenance']['refresh']['symbols']], ['unchanged', 'unchanged'])
        for entry, old in zip(manifest['entries'], self.manifest['entries']):
            self.assertEqual((self.output / entry['path']).read_bytes(), (self.base / old['path']).read_bytes())
        self.assertEqual(manifest['prepared_at'], self.now.isoformat())
        self.args[self.args.index('--base-manifest') + 1] = str(self.output / 'manifest.json')
        self.args[self.args.index('--base-sha256') + 1] = sha((self.output / 'manifest.json').read_bytes())
        self.args[self.args.index('--output') + 1] = str(self.root / 'next')
        self.args[self.args.index('--cutoff-exclusive') + 1] = '2024-02-02'
        self.now += dt.timedelta(days=1)
        result, text = self.run_refresh()
        self.assertEqual(result, 0, text)

    def test_all_inputs_and_base_evidence_reject_symlinks_and_hardlinks(self):
        files = [self.env, self.token, self.manifest_path, self.universe,
                 self.base / 'universe.json', next((self.base / 'raw').iterdir())]
        for path in files:
            with self.subTest(path=path.name):
                backup = path.with_name(path.name + '.original')
                path.rename(backup)
                path.symlink_to(backup)
                try:
                    result, text = self.run_refresh()
                    self.assertEqual((result, text), (1, 'blocked: symlink_path\n'))
                    self.assertFalse(self.calls)
                    self.assertFalse(self.output.exists())
                finally:
                    path.unlink()
                    backup.rename(path)
        os.link(self.env, self.root / 'env-alias')
        result, text = self.run_refresh()
        self.assertEqual((result, text), (1, 'blocked: unsafe_file_permissions\n'))
        self.assertFalse(self.calls)

    def test_pins_json_and_date_inputs_are_strict_and_do_not_echo_private_values(self):
        cases = [('--base-sha256', 'A' * 64, 'invalid_sha256'),
                 ('--universe-sha256', '0' * 63, 'invalid_sha256'),
                 ('--cutoff-exclusive', '2024-02-03', 'invalid_date_range'),
                 ('--start-date', '2024-02-01', 'invalid_date_range')]
        for flag, value, code in cases:
            with self.subTest(flag=flag):
                result, text = self.run_refresh(self.args + [flag, value])
                self.assertEqual((result, text), (1, 'blocked: ' + code + '\n'))
                self.assertFalse(self.calls)
                self.assertFalse(self.output.exists())
        raw = self.manifest_path.read_bytes().replace(b'"provider": "toss"', b'"provider": "other", "provider": "toss"')
        self.write(self.manifest_path, raw)
        args = self.args + ['--base-sha256', sha(raw)]
        result, text = self.run_refresh(args)
        self.assertEqual((result, text), (1, 'blocked: invalid_json\n'))
        self.assertFalse(self.calls)
        self.assertFalse(self.output.exists())

    def test_catalog_requires_both_markets_and_valid_metadata_before_http(self):
        variants = []
        single = json.loads(self.catalog_raw)
        single['instruments'] = single['instruments'][:1]
        variants.append(json.dumps(single).encode())
        variants.append(self.catalog_raw.replace(b'"point_in_time": false', b'"point_in_time": true'))
        variants.append(self.catalog_raw.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1'))
        for raw in variants:
            with self.subTest(raw=variants.index(raw)):
                self.universe.write_bytes(raw)
                result, text = self.run_refresh(self.args + ['--universe-sha256', sha(raw)])
                self.assertEqual((result, text), (1, 'blocked: invalid_universe\n'))
                self.assertFalse(self.calls)
                self.assertFalse(self.output.exists())

    def test_invalid_arguments_never_echo_private_paths_or_uncontrolled_parser_errors(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                result, text = self.run_refresh(self.args + ['--private-secret-path', str(self.env)])
            except SystemExit:
                self.fail('argument errors must be controlled status, not parser SystemExit')
        self.assertEqual((result, text), (1, 'blocked: invalid_arguments\n'))
        self.assertEqual(err.getvalue(), '')
        self.assertFalse(self.calls)
        self.assertFalse(self.output.exists())

    def test_all_96_catalog_identities_have_complete_lineage_or_none_publish(self):
        raw = (ROOT / 'universes/thematic-v1.json').read_bytes()
        self.catalog = json.loads(raw)
        self.catalog_raw = raw
        self.universe.write_bytes(raw)
        self.write(self.base / 'universe.json', raw)
        templates = {e['market']: e for e in self.manifest['entries']}
        expanded = []
        for item in self.catalog['instruments']:
            e = dict(templates[item['market']], **{k: item[k] for k in ('market', 'ticker', 'source_symbol')})
            e['path'] = item['market'] + '_' + item['ticker'] + '.csv'
            self.write(self.base / e['path'], (self.base / templates[item['market']]['path']).read_bytes())
            expanded.append(e)
        self.manifest.update(entries=expanded, universe=dict(path='universe.json', sha256=sha(raw)))
        self.save_base()
        self.args[self.args.index('--universe-sha256') + 1] = sha(raw)
        result, text = self.run_refresh()
        self.assertEqual(result, 0, text)
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertEqual(len(manifest['entries']), 96)
        self.assertEqual(len(self.calls), 96)
        symbols = manifest['provenance']['refresh']['symbols']
        self.assertEqual({(s['market'], s['ticker'], s['source_symbol']) for s in symbols},
                         {(s['market'], s['ticker'], s['source_symbol']) for s in self.catalog['instruments']})
        for symbol in symbols:
            self.assertEqual(symbol['base_coverage']['rows'], 760)
            self.assertEqual(symbol['tail_coverage']['rows'], 200)
            self.assertEqual(symbol['appended_rows'], 1)
            self.assertTrue(symbol['prefix_carried'])
        self.args[self.args.index('--output') + 1] = str(self.root / 'blocked-96')
        last_source = self.catalog['instruments'][-1]['source_symbol']
        self.calls.clear()
        def unavailable(*args):
            if parse_qs(urlparse(args[1]).query)['symbol'] == [last_source]:
                self.calls.append(args[1])
                return 404, {}, b'PRIVATE_PROVIDER_EVIDENCE'
            return self.send(*args)
        result, text = self.run_refresh(send=unavailable)
        self.assertEqual((result, text), (1, 'blocked: http_404\n'))
        failed = self.root / 'blocked-96'
        self.assertFalse((failed / 'manifest.json').exists())
        blocked = json.loads((failed / 'blocked.json').read_bytes())
        self.assertEqual(len(blocked['completed_entries']), 95)
        self.assertEqual(blocked['http_attempts'], 96)
        self.assertNotIn('PRIVATE_PROVIDER_EVIDENCE', text)

    def test_fallback_cannot_publish_a_partial_history_that_regresses_known_coverage(self):
        def partial(*args):
            if len(self.calls) == 1:
                self.dates = self.dates[:-3]
            status, headers, raw = self.send(*args)
            # Force the first tail to disagree, then return a nominally >500-row
            # full history that has lost the base's latest known completed bars.
            if len(self.calls) == 1:
                raw = raw.replace(b'"closePrice": 11', b'"closePrice": 10.5')
            return status, headers, raw
        result, text = self.run_refresh(send=partial)
        self.assertEqual((result, text), (1, 'blocked: history_coverage_regressed\n'))
        self.assertFalse((self.output / 'manifest.json').exists())
        self.assertEqual(json.loads((self.output / 'blocked.json').read_bytes())['errors'][0]['code'], 'history_coverage_regressed')

    def test_wall_budget_includes_post_http_validation_and_publication(self):
        original = self.m.p.immutable
        def late(path, raw):
            original(path, raw)
            if Path(path).name == 'US_BRK-B.toss.csv':
                self.clock = 1200.
        with patch.object(self.m.p, 'immutable', side_effect=late):
            result, text = self.run_refresh()
        self.assertEqual((result, text), (1, 'blocked: wall_budget_exhausted\n'))
        self.assertFalse((self.output / 'manifest.json').exists())
        self.assertEqual(json.loads((self.output / 'blocked.json').read_bytes())['http_attempts'], 2)

    def test_symbol_and_metadata_echoes_are_checked_on_tail_and_full_history(self):
        for name, stage, metadata, code in [
            ('tail-symbol', 1, dict(symbol='PRIVATE_WRONG_SYMBOL'), 'candle_metadata_mismatch'),
            ('fallback-symbol', 2, dict(symbol='PRIVATE_WRONG_SYMBOL'), 'candle_metadata_mismatch'),
            ('interval', 1, dict(interval='1m'), 'candle_metadata_mismatch'),
            ('adjusted', 1, dict(adjusted=False), 'candle_metadata_mismatch'),
            ('shape', 1, None, 'invalid_candle_response'),
        ]:
            with self.subTest(name=name):
                output = self.root / name
                args = self.args + ['--output', str(output)]
                self.calls.clear()
                def changed(*params):
                    status, headers, raw = self.send(*params)
                    value = json.loads(raw)
                    if stage == 2 and len(self.calls) == 1:
                        value['result']['candles'][20]['volume'] = 3
                    if len(self.calls) == stage:
                        if metadata is None:
                            value = {'secret': 'PRIVATE_METADATA_EVIDENCE'}
                        else:
                            value['result'].update(metadata)
                    return status, headers, json.dumps(value).encode()
                result, text = self.run_refresh(args, send=changed)
                self.assertEqual((result, text), (1, 'blocked: ' + code + '\n'))
                self.assertFalse((output / 'manifest.json').exists())
                self.assertNotIn('PRIVATE_', text)
                blocked = json.loads((output / 'blocked.json').read_bytes())
                self.assertEqual(blocked['http_attempts'], stage)

    def test_base_cannot_claim_bars_that_were_not_complete_at_acquisition(self):
        self.manifest['prepared_at'] = '2024-01-31T08:00:00+09:00'
        self.save_base()
        result, text = self.run_refresh()
        self.assertEqual((result, text), (1, 'blocked: invalid_base_metadata\n'))
        self.assertFalse(self.calls)
        self.assertFalse(self.output.exists())

    def test_original_raw_evidence_is_immutable_and_privately_referenced(self):
        original_raw = next((self.base / 'raw').iterdir())
        original_bytes = original_raw.read_bytes()
        def changed(*args):
            response = self.send(*args)
            self.write(original_raw, b'CHANGED_PRIVATE_RAW')
            return response
        result, text = self.run_refresh(send=changed)
        self.assertEqual((result, text), (1, 'blocked: base_changed\n'))
        self.assertFalse((self.output / 'manifest.json').exists())
        self.assertNotIn(str(self.base), text)
        # Restore original evidence only inside the synthetic fixture, then
        # ensure provenance links back to the base instead of copying its raw.
        self.write(original_raw, original_bytes)
        self.args[self.args.index('--output') + 1] = str(self.root / 'referenced')
        result, text = self.run_refresh()
        self.assertEqual(result, 0, text)
        manifest = json.loads((self.root / 'referenced/manifest.json').read_bytes())
        self.assertEqual(manifest['provenance']['refresh']['base_manifest_path'], str(self.manifest_path))
        self.assertNotIn(str(self.base), text)

    def test_refresh_never_writes_anywhere_inside_the_base(self):
        result, text = self.run_refresh(self.args + ['--output', str(self.base / 'new-child')])
        self.assertEqual((result, text), (1, 'blocked: mutable_base_path\n'))
        self.assertFalse(self.calls)
        self.assertFalse((self.base / 'new-child').exists())
        token = self.base / 'token.json'
        self.write(token, self.token.read_bytes())
        result, text = self.run_refresh(self.args + ['--token-file', str(token)])
        self.assertEqual((result, text), (1, 'blocked: mutable_base_path\n'))
        self.assertFalse(self.calls)
        self.assertFalse(token.with_name('token.json.collection.lock').exists())

    def test_quality_policy_and_original_provenance_paths_are_not_arbitrary_claims(self):
        original = json.loads(json.dumps(self.manifest))
        variants = [
            lambda b: b['quality'].update(completion_policy='not checked'),
            lambda b: b['quality'].update(history_start_policy='listing certified'),
            lambda b: b['provenance'].update(raw_directory='../outside'),
            lambda b: b['provenance'].update(request_log=str(self.env)),
            lambda b: b.update(provenance={'unknown': 'anything'}),
        ]
        for change in variants:
            with self.subTest(index=variants.index(change)):
                self.manifest = json.loads(json.dumps(original))
                change(self.manifest)
                self.save_base()
                result, text = self.run_refresh()
                self.assertEqual((result, text), (1, 'blocked: invalid_base_metadata\n'))
                self.assertFalse(self.calls)
                self.assertFalse(self.output.exists())

    def test_token_sidecar_mutex_files_cannot_be_aliased(self):
        for suffix in ('.collection.lock', '.issuance.lock'):
            with self.subTest(suffix=suffix):
                lock = self.token.with_name(self.token.name + suffix)
                alias = self.root / ('alias' + suffix)
                os.link(lock, alias)
                try:
                    result, text = self.run_refresh()
                    self.assertEqual((result, text), (1, 'blocked: unsafe_file_permissions\n'))
                    self.assertFalse(self.calls)
                    self.assertFalse(self.output.exists())
                finally:
                    alias.unlink()

    def test_every_overlap_date_and_ohlcv_component_controls_fallback(self):
        cases = [('none', None), ('one', None), ('missing-last', None), ('missing-interior', None)]
        cases += [(field, value) for field, value in [('openPrice', 10.1), ('highPrice', 12.1),
                                                    ('lowPrice', 8.9), ('closePrice', 10.9), ('volume', 1)]]
        for name, value in cases:
            with self.subTest(name=name):
                output = self.root / ('overlap-' + name)
                self.calls.clear()
                def change(*params):
                    status, headers, raw = self.send(*params)
                    if len(self.calls) == 1:
                        data = json.loads(raw)
                        candles = data['result']['candles']
                        if name == 'none':
                            data['result']['candles'] = candles[:1]
                        elif name == 'one':
                            data['result']['candles'] = candles[:2]
                        elif name == 'missing-last':
                            del candles[1]
                        elif name == 'missing-interior':
                            del candles[100]
                        else:
                            candles[150][name] = value
                        raw = json.dumps(data).encode()
                    return status, headers, raw
                result, text = self.run_refresh(self.args + ['--output', str(output)], send=change)
                self.assertEqual(result, 0, text)
                manifest = json.loads((output / 'manifest.json').read_bytes())
                self.assertEqual(manifest['provenance']['refresh']['symbols'][0]['mode'], 'full-refresh')
                self.assertEqual(manifest['entries'][0]['rows'], 761)
                self.assertEqual(len(self.calls), 6)

    def test_tail_and_fallback_and_auth_use_the_same_attempt_budget(self):
        self.token.unlink()
        def response(method, url, headers, body, timeout):
            if method == 'POST':
                self.calls.append(url)
                return 200, {}, b'{"access_token":"synthetic-token","expires_in":3600}'
            status, response_headers, raw = self.send(method, url, headers, body, timeout)
            if len(self.calls) == 2:
                raw = raw.replace(b'"closePrice": 11', b'"closePrice": 10.5')
            return status, response_headers, raw
        result, text = self.run_refresh(self.args + ['--max-attempts', '4'], send=response)
        self.assertEqual((result, text), (1, 'blocked: attempt_budget_exhausted\n'))
        blocked = json.loads((self.output / 'blocked.json').read_bytes())
        self.assertEqual(blocked['http_attempts'], 4)
        self.assertEqual(len(self.calls), 4)
        self.assertFalse((self.output / 'manifest.json').exists())
        log = (self.output / 'requests.jsonl').read_text()
        self.assertNotIn('synthetic-secret', log)
        self.assertNotIn('synthetic-token', log)

    def test_original_collection_mutex_wait_is_inside_shared_wall_budget(self):
        import fcntl
        lock = self.token.with_name(self.token.name + '.collection.lock')
        with lock.open('r+') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result, text = self.run_refresh(self.args + ['--max-minutes', '.001'])
        self.assertEqual((result, text), (1, 'blocked: wall_budget_exhausted\n'))
        self.assertFalse(self.calls)
        self.assertFalse((self.output / 'manifest.json').exists())
        self.assertEqual(json.loads((self.output / 'blocked.json').read_bytes())['http_attempts'], 0)

    def test_tail_order_currency_ohlcv_and_cursor_fail_without_fallback(self):
        cases = [('duplicate', 'nondecreasing_page_timestamps'), ('order', 'nondecreasing_page_timestamps'),
                 ('cursor', 'cursor_without_progress'), ('currency', 'currency_mismatch'),
                 ('ohlcv', 'invalid_ohlcv'), ('oversized', 'invalid_page')]
        for name, code in cases:
            with self.subTest(name=name):
                output = self.root / name
                self.calls.clear()
                def bad(*params):
                    status, headers, raw = self.send(*params)
                    data = json.loads(raw)
                    candles = data['result']['candles']
                    if name == 'duplicate':
                        candles[1] = candles[0]
                    elif name == 'order':
                        candles.reverse()
                    elif name == 'cursor':
                        data['result']['nextBefore'] = '2024-02-01T00:00:00+09:00'
                    elif name == 'currency':
                        candles[0]['currency'] = 'USD'
                    elif name == 'ohlcv':
                        candles[0]['volume'] = -1
                    elif name == 'oversized':
                        candles.append(candles[-1])
                    return status, headers, json.dumps(data).encode()
                result, text = self.run_refresh(self.args + ['--output', str(output)], send=bad)
                self.assertEqual((result, text), (1, 'blocked: ' + code + '\n'))
                self.assertEqual(len(self.calls), 1)
                self.assertFalse((output / 'manifest.json').exists())

    def test_aggregated_collect_universe_seed_paths_are_supported(self):
        batch = self.base / 'batches/0000'
        batch.mkdir(parents=True, mode=0o700)
        batch.parent.chmod(0o700)
        child_raw = self.manifest_path.read_bytes()
        self.write(batch / 'manifest.json', child_raw)
        for entry in self.manifest['entries']:
            old = self.base / entry['path']
            old.rename(batch / entry['path'])
            entry['path'] = 'batches/0000/' + entry['path']
        self.manifest['provenance'] = dict(batch_manifests=[dict(path='batches/0000/manifest.json', sha256=sha(child_raw))],
                                           plan_sha256='0' * 64, reserved_attempts=600)
        self.save_base()
        result, text = self.run_refresh()
        self.assertEqual(result, 0, text)
        self.assertEqual(len(self.calls), 2)
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertTrue(all('/' not in e['path'] for e in manifest['entries']))

    def test_existing_snapshot_is_never_overwritten(self):
        self.assertEqual(self.run_refresh()[0], 0)
        before = {str(f): f.read_bytes() for f in self.output.rglob('*') if f.is_file()}
        self.calls.clear()
        result, text = self.run_refresh()
        self.assertEqual((result, text), (1, 'blocked: output_already_exists\n'))
        self.assertFalse(self.calls)
        self.assertEqual(before, {str(f): f.read_bytes() for f in self.output.rglob('*') if f.is_file()})

    def test_output_changed_after_validation_cannot_publish_complete(self):
        def changed(*params):
            response = self.send(*params)
            if len(self.calls) == 2:
                path = self.output / 'KR_00AB12.toss.csv'
                self.write(path, b'PRIVATE_TAMPERED_CSV')
            return response
        result, text = self.run_refresh(send=changed)
        self.assertEqual((result, text), (1, 'blocked: output_changed\n'))
        self.assertFalse((self.output / 'manifest.json').exists())
        blocked = json.loads((self.output / 'blocked.json').read_bytes())
        self.assertEqual(blocked['universe'], dict(path='universe.json', sha256=sha(self.catalog_raw)))
        self.assertEqual(blocked['provenance']['refresh']['base_manifest_sha256'], sha(self.manifest_path.read_bytes()))

    def test_large_finite_min_interval_uses_wall_budget_not_an_undocumented_cap(self):
        result, text = self.run_refresh(self.args + ['--min-interval', '1801'])
        self.assertEqual((result, text), (1, 'blocked: wall_budget_exhausted\n'))
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.output / 'manifest.json').exists())

    def test_a_refreshed_base_with_corrupt_symbol_lineage_blocks_before_http(self):
        self.assertEqual(self.run_refresh()[0], 0)
        path = self.output / 'manifest.json'
        manifest = json.loads(path.read_bytes())
        manifest['provenance']['refresh']['symbols'] = []
        self.write(path, json.dumps(manifest).encode())
        self.now += dt.timedelta(days=1)
        self.calls.clear()
        args = self.args + ['--base-manifest', str(path), '--base-sha256', sha(path.read_bytes()),
                            '--cutoff-exclusive', '2024-02-02', '--output', str(self.root / 'bad-lineage')]
        result, text = self.run_refresh(args)
        self.assertEqual((result, text), (1, 'blocked: invalid_base_metadata\n'))
        self.assertFalse(self.calls)
        self.assertFalse((self.root / 'bad-lineage').exists())

    def test_base_pin_is_checked_before_http(self):
        self.manifest_path.write_bytes(self.manifest_path.read_bytes() + b' ')
        result, text = self.run_refresh()
        self.assertEqual((result, text), (1, 'blocked: base_hash_mismatch\n'))
        self.assertFalse(self.calls)
        self.assertFalse(self.output.exists())

    def test_exact_catalog_hash_is_checked_before_http(self):
        self.universe.write_bytes(self.catalog_raw + b' ')
        result, text = self.run_refresh()
        self.assertEqual((result, text), (1, 'blocked: universe_hash_mismatch\n'))
        self.assertFalse(self.calls)
        self.assertFalse(self.output.exists())
