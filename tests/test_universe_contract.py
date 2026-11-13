"""Offline UniverseJSONv1 contract tests (shared with native loader)."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def catalog():
    return {'schema_version': 1, 'universe_id': 'synthetic-57',
            'classification_as_of': '2026-11-10', 'point_in_time': False,
            'selection_policy': 'Current hypotheses only',
            'limitations': ['Not a historical membership universe'],
            'instruments': [{'market': 'US', 'ticker': 'BRK-B',
                             'source_symbol': 'BRK.B', 'themes': ['quality']}]}


def validator():
    path = ROOT / 'tools/universe_contract.py'
    if not path.exists():
        raise AssertionError('shared UniverseJSONv1 validator missing')
    spec = importlib.util.spec_from_file_location('universe_contract', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_universe


class UniverseContract(unittest.TestCase):
    def test_exact_fields_types_version_false_pit_and_nonempty_metadata(self):
        cases = [None, [], {}, dict(catalog(), extra=True)]
        for field in catalog():
            value = catalog()
            del value[field]
            cases.append(value)
        for field, invalids in {
            'schema_version': [True, 1.0, '1', 2],
            'point_in_time': [True, 0, None, 'false'],
            'selection_policy': ['', '  ', None, 7],
            'limitations': [[], '', [''], ['  '], [None]],
            'instruments': [[], {}, None],
        }.items():
            cases.extend(dict(catalog(), **{field: bad}) for bad in invalids)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validator()(json.dumps(value).encode())

    def test_strict_dates_and_lowercase_bounded_slugs(self):
        for field, bads in {
            'classification_as_of': ['20261110', '2026-1-10', '2026-02-30',
                                     '0000-01-01', '２０２６-11-10', 20261110, None],
            'universe_id': ['', '-x', '_x', 'Upper', 'has.dot', 'x' * 65, 'é', None],
        }.items():
            for bad in bads:
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    validator()(json.dumps(dict(catalog(), **{field: bad})).encode())
        for slug in ['a', '0', 'a_b-1', 'x' * 64]:
            value = dict(catalog(), universe_id=slug)
            self.assertEqual(validator()(json.dumps(value).encode()), value)

    def test_instrument_exact_fields_market_identifiers_and_theme_slugs(self):
        instrument = catalog()['instruments'][0]
        bad_entries = [None, {}, dict(instrument, extra=1)]
        for field in instrument:
            item = dict(instrument)
            del item[field]
            bad_entries.append(item)
        bad_entries += [dict(instrument, market=m) for m in ['us', 'JP', None, []]]
        for field in ['ticker', 'source_symbol']:
            for market, bads in [('US', ['', '.A', '-A', 'brk.b', 'A/B', 'Á', 'A' * 25, None, 7]),
                                 ('KR', ['12345', '1234567', 'abc123', '１２３４５６', 'A-1234', None])]:
                bad_entries += [dict(instrument, market=market, **{field: bad}) for bad in bads]
        bad_entries += [dict(instrument, themes=bad) for bad in
                        [[], 'quality', ['quality', 'quality'], ['Upper'], ['-x'], ['a' * 65], [None]]]
        for item in bad_entries:
            with self.subTest(item=item), self.assertRaises(ValueError):
                validator()(json.dumps(dict(catalog(), instruments=[item])).encode())
        for market, symbol in [('US', '0'), ('US', 'A' * 24), ('US', 'BRK.B'), ('KR', '00AB12')]:
            value = dict(catalog(), instruments=[dict(instrument, market=market,
                                                      ticker=symbol, source_symbol=symbol)])
            self.assertEqual(validator()(json.dumps(value).encode()), value)

    def test_duplicate_logical_and_source_identities_and_catalog_limit(self):
        item = catalog()['instruments'][0]
        for entries in [[item, item], [item, dict(item, source_symbol='OTHER')],
                        [item, dict(item, ticker='OTHER')]]:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                validator()(json.dumps(dict(catalog(), instruments=entries)).encode())
        entries = [dict(item, ticker=f'A{i}', source_symbol=f'A{i}') for i in range(512)]
        value = dict(catalog(), instruments=entries)
        self.assertEqual(validator()(json.dumps(value).encode()), value)
        entries.append(dict(item, ticker='EXTRA', source_symbol='EXTRA'))
        with self.assertRaises(ValueError):
            validator()(json.dumps(value).encode())

    def test_strict_utf8_json_duplicate_keys_at_every_depth_and_nonfinite(self):
        raw = json.dumps(catalog()).encode()
        bads = [b'\xff', b'{} trailing', b'\xef\xbb\xbf' + raw,
                raw.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1'),
                raw.replace(b'"market": "US"', b'"market": "US", "market": "US"'),
                raw.replace(b'"selection_policy": "Current hypotheses only"', b'"selection_policy": NaN'),
                raw.replace(b'"schema_version": 1', b'"schema_version": Infinity')]
        for bad in bads:
            with self.subTest(raw=bad), self.assertRaises(ValueError):
                validator()(bad)

    def test_json_strings_must_be_valid_unicode_scalars_like_native_loader(self):
        for field in ['selection_policy', 'limitations']:
            value = dict(catalog(), **{field: '\ud800' if field == 'selection_policy' else ['\udfff']})
            with self.subTest(field=field), self.assertRaises(ValueError):
                validator()(json.dumps(value).encode())
        value = dict(catalog(), selection_policy='한글 thematic 🚀')
        self.assertEqual(validator()(json.dumps(value, ensure_ascii=False).encode()), value)

    def test_single_market_catalog_validates_without_private_path_or_normalization(self):
        value = catalog()
        self.assertEqual(validator()(json.dumps(value).encode()), value)
