#!/usr/bin/env python3
"""Issue #61: private, bounded metadata evidence, never history/PIT certification."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import time
if __package__:
    from . import prepare_toss as p
else:
    import prepare_toss as p


class MetadataClient(p.Client):
    def _validate_request(self, path, params, form):
        if path == '/oauth2/token':
            return super()._validate_request(path, params, form)
        if path not in ('/api/v1/stocks', '/api/v1/market-calendar/KR', '/api/v1/market-calendar/US'):
            raise p.Blocked('endpoint_not_allowed')
        key = 'symbols' if path == '/api/v1/stocks' else 'date'
        if form is not None or not isinstance(params, dict) or set(params) != {key}:
            raise p.Blocked('parameter_not_allowed')
        value = params[key]
        if not isinstance(value, str):
            raise p.Blocked('parameter_not_allowed')
        if key == 'date':
            p.iso_date(value)
        elif not 1 <= len(value.split(',')) <= 200 or any(
                not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,23}', s) for s in value.split(',')):
            raise p.Blocked('parameter_not_allowed')


def query(auth, endpoint, params):
    token = auth.get_token()
    try:
        return auth.client.request(endpoint, params, token=token)
    except p.Unauthorized:
        if auth.refreshed:
            raise p.Blocked('repeated_http_401') from None
        auth.refreshed = True
        token = auth.get_token(rejected=token)
        try:
            return auth.client.request(endpoint, params, token=token)
        except p.Unauthorized:
            raise p.Blocked('repeated_http_401') from None


def main(argv=None, *, send=p.transport, monotonic=time.monotonic, sleep=time.sleep):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'env-file', 'token-file', 'universe-file', 'universe-sha256', 'calendar-dates'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--max-attempts', type=int, default=20)
    parser.add_argument('--max-seconds', type=float, default=120)
    parser.add_argument('--min-interval', type=float, default=.5)
    args = parser.parse_args(argv)
    output = client = None
    report = {'schema_version': 1, 'history_certified': False, 'point_in_time': False,
              'documentation_vs_actual': {'openapi_version': '1.2.28',
                  'documented_stock_date_fields': ['listDate', 'delistDate'],
                  'current_status_metadata_documented': True,
                  'stock_dates_nullable': True, 'calendar_date_query_documented': True,
                  'historical_retention': 'unverified', 'sector_as_of_supported': False,
                  'actual': 'private_probe_evidence_only_not_history_certification'}, 'probes': []}
    code = None
    try:
        if (not 1 <= args.max_attempts <= 20 or not math.isfinite(args.max_seconds)
                or not 0 < args.max_seconds <= 120 or not math.isfinite(args.min_interval)
                or not .5 <= args.min_interval <= 120):
            raise p.Blocked('invalid_budget')
        dates = args.calendar_dates.split(',')
        if not 1 <= len(dates) <= 4 or len(set(dates)) != len(dates):
            raise p.Blocked('invalid_calendar_dates')
        for day in dates:
            p.iso_date(day)
        if not re.fullmatch(r'[a-f0-9]{64}', args.universe_sha256):
            raise p.Blocked('invalid_universe_sha256')
        raw = Path(args.universe_file).read_bytes()
        if hashlib.sha256(raw).hexdigest() != args.universe_sha256:
            raise p.Blocked('universe_hash_mismatch')
        try:
            instruments = p.validate_universe(raw)['instruments']
        except (ValueError, RecursionError):
            raise p.Blocked('invalid_universe') from None
        if len(instruments) != 96 or {i['market'] for i in instruments} != {'KR', 'US'}:
            raise p.Blocked('expected_96_instruments')
        probes = [{'endpoint': '/api/v1/stocks',
                   'params': {'symbols': ','.join(i['source_symbol'] for i in instruments)}}]
        probes += [{'endpoint': '/api/v1/market-calendar/' + market, 'params': {'date': day}}
                   for day in dates for market in ('KR', 'US')]
        candidate = p.private_path(args.output, exists=False)
        if candidate.exists():
            raise p.Blocked('output_already_exists')
        if not candidate.parent.is_dir():
            raise p.Blocked('output_parent_missing')
        token = p.private_path(args.token_file, exists=Path(args.token_file).exists())
        credentials = p.read_env(args.env_file)
        candidate.mkdir(mode=0o700)
        output = candidate
        report['universe_sha256'] = args.universe_sha256
        p.immutable(output / 'universe.json', raw)
        p.immutable(output / 'plan.json', p.json_bytes({'probes': probes,
                    'universe_sha256': args.universe_sha256, 'max_attempts': args.max_attempts,
                    'max_seconds': args.max_seconds, 'min_interval': args.min_interval}))
        client = MetadataClient(output, args.max_attempts, args.max_seconds, args.min_interval,
                                send, monotonic, sleep)
        with p.file_lock(token.with_name(token.name + '.collection.lock'), client):
            auth = p.Auth(client, token, credentials)
            for probe in probes:
                record = dict(probe, result='blocked', sha256=None, raw_path=None)
                first = client.attempts
                try:
                    query(auth, probe['endpoint'], probe['params'])
                    record['result'] = 'observed_not_certified'
                except p.Blocked as error:
                    record['code'] = str(error)
                    if str(error) not in ('http_400', 'http_404'):
                        raise
                    record['result'] = 'unsupported'
                finally:
                    events = [json.loads(line) for line in (output / 'requests.jsonl').read_text().splitlines()]
                    ends = [e for e in events if e['event'] == 'end' and e['attempt'] > first
                            and e['endpoint'] == probe['endpoint']]
                    if ends:
                        record.update({key: ends[-1][key] for key in ('sha256', 'raw_path', 'status')})
                    report['probes'].append(record)
            if client.clock() >= client.deadline:
                raise p.Blocked('wall_budget_exhausted')
    except (Exception, KeyboardInterrupt) as error:
        code = str(error) if isinstance(error, p.Blocked) else 'interrupted' if isinstance(error, KeyboardInterrupt) else 'internal_failure'
    if output is not None:
        report.update(status='blocked' if code else 'complete', code=code,
                      http_attempts=client.attempts if client else 0)
        try:
            p.immutable(output / 'report.json', p.json_bytes(report))
        except OSError:
            code = 'report_write_failed'
    print('blocked: ' + code if code else 'complete: private metadata evidence written; history not certified')
    return 1 if code else 0


if __name__ == '__main__':
    raise SystemExit(main())

