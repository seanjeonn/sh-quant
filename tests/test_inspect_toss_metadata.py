"""Issue #61: synthetic-only, bounded read-only metadata inspection."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlparse, parse_qs
from tools import prepare_toss as p


class PolicyHook(unittest.TestCase):
    def test_request_dispatches_protected_policy_without_default_allowance_drift(self):
        class Denied(p.Client):
            def _validate_request(self, path, params, form):
                raise p.Blocked('custom_policy')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = Denied(root, 1, 5, .5, send=lambda *a: self.fail('transport'))
            with self.assertRaisesRegex(p.Blocked, 'custom_policy'):
                client.request('/oauth2/token')
            default = object.__new__(p.Client)
            for endpoint in ['/api/v1/stocks', '/api/v1/market-calendar/KR', '/api/v1/orders']:
                with self.assertRaisesRegex(p.Blocked, 'endpoint_not_allowed'):
                    default._validate_request(endpoint, {}, None)
            default._validate_request('/oauth2/token', None, {'grant_type': 'client_credentials'})
            default._validate_request('/api/v1/candles', {'symbol': 'SPY'}, None)
            with self.assertRaisesRegex(p.Blocked, 'parameter_not_allowed'):
                default._validate_request('/api/v1/candles', {'extra': 'x'}, None)


class MetadataPolicy(unittest.TestCase):
    def test_exact_get_only_whitelist_and_private_failure_body(self):
        from tools import inspect_toss_metadata as m
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            def send(*args):
                calls.append(args)
                return 404, {}, b'{"secret":"private-only"}'
            client = m.MetadataClient(root, 20, 120, .5, send=send)
            valid = [('/api/v1/stocks', {'symbols': 'SPY,BRK.B'}),
                     ('/api/v1/market-calendar/KR', {'date': '2015-01-01'}),
                     ('/api/v1/market-calendar/US', {'date': '2024-02-29'})]
            for path, params in valid:
                client._validate_request(path, params, None)
                with self.assertRaises(p.Blocked):
                    client._validate_request(path, params, {})
            invalid = [('/api/v1/candles', {'symbol': 'SPY'}),
                       ('/api/v1/accounts', {}), ('/api/v1/orders', {}),
                       ('/api/v1/quotes', {}), ('/api/v1/rankings', {}),
                       ('/api/v1/sectors', {}), ('/api/v1/stocks/', {'symbols': 'SPY'}),
                       ('/api/v1/stocks', {'symbols': 'SPY', 'extra': 'x'}),
                       ('/api/v1/stocks', {'symbols': 'SPY&secret=x'}),
                       ('/api/v1/stocks', {'symbols': ','.join(['SPY'] * 201)}),
                       ('/api/v1/market-calendar/US', {'date': '2023-02-29'}),
                       ('/api/v1/market-calendar/US', {})]
            for path, params in invalid:
                with self.assertRaises(p.Blocked):
                    client._validate_request(path, params, None)
            with self.assertRaisesRegex(p.Blocked, 'http_404'):
                client.request(*valid[0])
            self.assertEqual(calls[0][0], 'GET')
            raw = root / 'raw/000001.bin'
            self.assertEqual(raw.read_bytes(), b'{"secret":"private-only"}')
            self.assertEqual(raw.stat().st_mode & 0o777, 0o600)
            end = json.loads((root / 'requests.jsonl').read_text().splitlines()[-1])
            self.assertEqual(end['sha256'], hashlib.sha256(raw.read_bytes()).hexdigest())


class Inspection(unittest.TestCase):
    def setUp(self):
        from tools import inspect_toss_metadata as m
        from test_universe_contract import catalog
        self.m = m
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.root.chmod(0o700)
        self.env, self.token = self.root / 'env', self.root / 'token'
        p.immutable(self.env, b'TOSS_CLIENT_ID=fake\nTOSS_CLIENT_SECRET=secret-fixture\n')
        p.immutable(self.token, p.json_bytes({'access_token': 'fake-token', 'expires_at': 9999999999}))
        universe = catalog()
        universe['instruments'] = [{'market': 'US', 'ticker': f'S{i}', 'source_symbol': f'S{i}', 'themes': ['test']} for i in range(48)] + [
            {'market': 'KR', 'ticker': f'{i:06d}', 'source_symbol': f'{i:06d}', 'themes': ['test']} for i in range(48)]
        self.universe = self.root / 'universe.json'
        self.raw = p.json_bytes(universe)
        self.universe.write_bytes(self.raw)
        self.output = self.root / 'inspection'
        self.args = ['--env-file', str(self.env), '--token-file', str(self.token),
                     '--universe-file', str(self.universe), '--universe-sha256', hashlib.sha256(self.raw).hexdigest(),
                     '--output', str(self.output), '--calendar-dates', '2015-01-01,2024-02-29']
        self.clock, self.calls = 0., []

    def send(self, method, url, headers, body, timeout):
        self.calls.append((method, url, body))
        return 200, {}, b'{"result":{"secret":"not-in-report","listDate":null}}'

    def run_cli(self, extra=(), send=None):
        def sleep(seconds):
            self.clock += seconds
        with contextlib.redirect_stdout(io.StringIO()) as out:
            result = self.m.main(self.args + list(extra), send=send or self.send,
                                 monotonic=lambda: self.clock, sleep=sleep)
        self.assertNotIn('secret-fixture', out.getvalue())
        self.assertNotIn('fake-token', out.getvalue())
        return result, out.getvalue()

    def test_plan_report_lineage_and_private_artifacts_no_overwrite(self):
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(len(self.calls), 5)
        self.assertEqual(len(parse_qs(urlparse(self.calls[0][1]).query)['symbols'][0].split(',')), 96)
        self.assertTrue(all(method == 'GET' and body is None for method, _, body in self.calls))
        report = json.loads((self.output / 'report.json').read_bytes())
        self.assertFalse(report['history_certified'])
        self.assertFalse(report['point_in_time'])
        self.assertEqual(report['documentation_vs_actual']['historical_retention'], 'unverified')
        self.assertEqual(report['http_attempts'], 5)
        self.assertEqual(len(report['probes']), 5)
        self.assertNotIn('not-in-report', json.dumps(report))
        self.assertEqual(report['universe_sha256'], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual((self.output / 'universe.json').read_bytes(), self.raw)
        plan = json.loads((self.output / 'plan.json').read_bytes())
        self.assertEqual(len(plan['probes']), 5)
        for probe in report['probes']:
            self.assertEqual(probe['result'], 'observed_not_certified')
            self.assertEqual(probe['sha256'], hashlib.sha256((self.output / probe['raw_path']).read_bytes()).hexdigest())
        for item in [self.output, *self.output.rglob('*')]:
            self.assertEqual(item.stat().st_mode & 0o777, 0o700 if item.is_dir() else 0o600)
        before = (self.output / 'report.json').read_bytes()
        self.assertEqual(self.run_cli()[0], 1)
        self.assertEqual(len(self.calls), 5)
        self.assertEqual((self.output / 'report.json').read_bytes(), before)

    def report(self):
        return json.loads((self.output / 'report.json').read_bytes())

    def test_unsupported_dates_continue_without_today_fallback(self):
        def send(*args):
            self.send(*args)
            status = 200 if '/stocks?' in args[1] else 400 if '/KR?' in args[1] else 404
            return status, {}, b'{"secret":"private-error"}'
        self.assertEqual(self.run_cli(send=send)[0], 0)
        self.assertEqual([r['result'] for r in self.report()['probes']],
                         ['observed_not_certified'] + ['unsupported'] * 4)
        self.assertEqual(len(self.calls), 5)
        for _, url, _ in self.calls[1:]:
            self.assertIn(parse_qs(urlparse(url).query)['date'][0], ['2015-01-01', '2024-02-29'])
        self.assertNotIn('private-error', json.dumps(self.report()))

    def test_all_auth_retry_and_probe_attempts_share_budget(self):
        self.token.unlink()
        def send(*args):
            self.send(*args)
            if '/oauth2/token' in args[1]:
                return 200, {}, b'{"access_token":"issued-fixture","expires_in":3600}'
            return 500, {}, b'{"error":"private-retry"}'
        self.assertEqual(self.run_cli(['--max-attempts', '3'], send=send)[0], 1)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.report()['code'], 'attempt_budget_exhausted')
        self.assertEqual(self.report()['http_attempts'], 3)
        self.assertFalse((self.output / 'raw/000001.bin').exists())
        self.assertEqual(len(list((self.output / 'raw').iterdir())), 2)
        self.assertNotIn('issued-fixture', (self.output / 'requests.jsonl').read_text())

    def test_unauthorized_refresh_once_then_abort_no_secret_output(self):
        def send(*args):
            self.send(*args)
            if '/oauth2/token' in args[1]:
                return 200, {}, b'{"access_token":"new-fixture","expires_in":3600}'
            return 401, {}, b'{"secret":"private-401"}'
        self.assertEqual(self.run_cli(send=send)[0], 1)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.report()['code'], 'repeated_http_401')
        self.assertEqual(sum('/oauth2/token' in url for _, url, _ in self.calls), 1)
        self.assertEqual(len(list((self.output / 'raw').iterdir())), 2)

    def test_default_twenty_attempt_budget_includes_failed_probes(self):
        def send(*args):
            self.send(*args)
            return (200 if len(self.calls) % 5 == 0 else 500), {}, b'{}'
        self.assertEqual(self.run_cli(send=send)[0], 1)
        self.assertEqual(len(self.calls), 20)
        self.assertEqual(self.report()['http_attempts'], 20)
        self.assertEqual(self.report()['code'], 'attempt_budget_exhausted')
        self.assertEqual(len(list((self.output / 'raw').iterdir())), 20)

    def test_once_refreshed_later_401_does_not_issue_another_token(self):
        metadata = 0
        def send(*args):
            nonlocal metadata
            self.send(*args)
            if '/oauth2/token' in args[1]:
                return 200, {}, b'{"access_token":"new-fixture","expires_in":3600}'
            metadata += 1
            return (200 if metadata == 2 else 401), {}, b'{}'
        self.assertEqual(self.run_cli(send=send)[0], 1)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(self.report()['code'], 'repeated_http_401')
        self.assertEqual(sum('/oauth2/token' in url for _, url, _ in self.calls), 1)

    def test_four_dates_at_most_nine_metadata_requests(self):
        self.assertEqual(self.run_cli(['--calendar-dates', '2015-01-01,2020-01-01,2023-01-01,2024-01-01'])[0], 0)
        self.assertEqual(len(self.calls), 9)

    def test_403_aborts_and_preserves_private_failure(self):
        def send(*args):
            self.send(*args)
            return 403, {}, b'{"secret":"private-403"}'
        self.assertEqual(self.run_cli(send=send)[0], 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.report()['code'], 'http_403')
        self.assertEqual((self.output / 'raw/000001.bin').read_bytes(), b'{"secret":"private-403"}')

    def test_wall_deadline_and_pacing_share_client_budget(self):
        self.assertEqual(self.run_cli(['--max-seconds', '.25'])[0], 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.report()['code'], 'wall_budget_exhausted')

    def test_preflight_budget_dates_hash_permissions_and_git_guards(self):
        cases = [(['--max-attempts', '21'], 'invalid_budget'),
                 (['--max-seconds', '121'], 'invalid_budget'),
                 (['--max-seconds', 'nan'], 'invalid_budget'),
                 (['--min-interval', '.49'], 'invalid_budget'),
                 (['--calendar-dates', '2015-01-01,' * 4 + '2024-01-01'], 'invalid_calendar_dates'),
                 (['--calendar-dates', '2024-02-30'], 'invalid_date'),
                 (['--universe-sha256', 'bad'], 'invalid_universe_sha256'),
                 (['--universe-sha256', '0' * 64], 'universe_hash_mismatch')]
        for extra, code in cases:
            with self.subTest(code=code, extra=extra):
                self.assertEqual(self.run_cli(extra), (1, 'blocked: ' + code + '\n'))
                self.assertFalse(self.output.exists())
        self.env.chmod(0o644)
        self.assertEqual(self.run_cli()[0], 1)
        self.assertFalse(self.output.exists())
        self.env.chmod(0o600)
        self.token.chmod(0o644)
        self.assertEqual(self.run_cli()[0], 1)
        self.token.chmod(0o600)
        self.root.chmod(0o755)
        self.assertEqual(self.run_cli()[0], 1)
        self.root.chmod(0o700)
        checkout = self.root / 'repo'
        checkout.mkdir(mode=0o700)
        (checkout / '.git').mkdir()
        self.assertEqual(self.run_cli(['--output', str(checkout / 'new')])[0], 1)
        self.assertFalse((checkout / 'new').exists())
        link = self.root / 'linked'
        link.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.run_cli(['--output', str(link / 'new')])[0], 1)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
