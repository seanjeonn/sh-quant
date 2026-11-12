"""Synthetic policy fixtures only; not market evidence."""
import copy
import unittest
import json
import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import patch
from tools import research_contract as c


def plan() -> dict[str, Any]:
    sid = '2026-11-10_synthetic'
    return dict(schema_version=2, set_id=sid, timezone='Asia/Seoul', markets=['US', 'KR'],
                hypothesis='Synthetic hypothesis', tracking_issue='https://github.com/seanjeonn/sh-quant/issues/30',
                next_experiment=dict(
                    hypothesis='Test whether a five-bar close filter reduces synthetic turnover.',
                    reason='The current threshold rule does not constrain rapid position changes.'),
                engine_commit='a'*40, cargo_lock_sha256='b'*64, binary_sha256='c'*64,
                data_manifest_sha256='d'*64, holdout_status='exposed',
                machine_policy=dict(selection='mean_is_sharpe_v1', evaluation='sharpe_excess_mdd_v1'),
                baseline=dict(run_id=sid+'__baseline', parameters={'n': 1}, signal='close > 1'),
                variants=[dict(run_id=sid+'__v00'+str(n), parameters={'n': n}, signal='close > '+str(n)) for n in (2, 3)],
                budget=dict(max_attempts=12, max_wall_minutes=120, max_repairs=3))


def entries(p):
    return [dict(id=v['run_id'], status='ok', markets={m: {s: dict(sharpe='1', cagr='0.1', mdd='-0.2', excess_cagr='0') for s in ('is', 'oos')} for m in ('US', 'KR')}) for v in [p['baseline']]+p['variants']]


class ContractTests(unittest.TestCase):
    def test_selection_exact_decimal_and_no_oos_ranking(self):
        p = plan(); e = entries(p)
        e[1]['markets']['US']['is']['sharpe'] = '1.000000000000000000000000000001'
        result = c.select_candidate(p, e)
        self.assertEqual(result['selected_run_id'], e[1]['id'])
        self.assertIsInstance(result['ranking'][0]['mean_is_sharpe'], str)
        for row in e:
            for m in ('US', 'KR'): row['markets'][m]['oos']['sharpe'] = '-999'
        self.assertEqual(c.select_candidate(p, e), result)

    def test_selection_ties_baseline_then_id_and_cagr_mdd(self):
        p = plan(); e = entries(p)
        self.assertEqual(c.select_candidate(p, list(reversed(e)))['selected_run_id'], e[0]['id'])
        for i in (1, 2):
            e[i]['markets']['US']['is']['cagr'] = '0.2'
        self.assertEqual(c.select_candidate(p, e)['selected_run_id'], e[1]['id'])
        e[2]['markets']['KR']['is']['mdd'] = '-0.1'
        self.assertEqual(c.select_candidate(p, e)['selected_run_id'], e[2]['id'])
    def test_evaluation_accept_reject_defer_and_claim_rejection(self):
        p = plan(); e = entries(p); rid = e[0]['id']
        self.assertEqual(c.evaluate_candidate(p, e, rid)['conclusion'], 'accept')
        for m in ('US', 'KR'): e[0]['markets'][m]['oos']['excess_cagr'] = '-0.1'
        self.assertEqual(c.evaluate_candidate(p, e, rid)['conclusion'], 'reject')
        e[0]['markets']['US']['oos']['excess_cagr'] = '0'
        self.assertEqual(c.evaluate_candidate(p, e, rid)['conclusion'], 'defer')
        with self.assertRaises(c.ContractError): c.evaluate_candidate(p, e, e[1]['id'])

    def test_accept_boundaries_and_reject_sharpe_comparison(self):
        p = plan(); e = entries(p)
        e[1]['markets']['US']['is']['sharpe'] = '2'
        rid = e[1]['id']
        self.assertTrue(c.evaluate_candidate(p, e, rid)['criteria_evidence']['accept'])
        e[1]['markets']['US']['oos']['sharpe'] = '0'
        self.assertEqual(c.evaluate_candidate(p, e, rid)['conclusion'], 'defer')
        for m in ('US', 'KR'):
            e[1]['markets'][m]['oos'].update(sharpe='2', excess_cagr='-1', mdd='-0.3')
        self.assertEqual(c.evaluate_candidate(p, e, rid)['conclusion'], 'defer')
        for m in ('US', 'KR'): e[1]['markets'][m]['oos']['sharpe'] = '1'
        self.assertEqual(c.evaluate_candidate(p, e, rid)['conclusion'], 'reject')

    def test_metrics_and_candidate_coverage_fail_closed(self):
        p = plan()
        for value in (None, True, 'NaN', 'Infinity', '-Infinity', {}, 'provider-secret', float('nan')):
            e = entries(p); e[0]['markets']['US']['oos']['sharpe'] = value
            with self.subTest(value=type(value).__name__), self.assertRaises(c.ContractError) as caught:
                c.select_candidate(p, e)
            self.assertNotIn('provider-secret', str(caught.exception))
        for mode in ('missing', 'duplicate', 'extra', 'failed', 'null-market', 'optional-nan'):
            e = entries(p)
            if mode == 'missing': e.pop()
            if mode == 'duplicate': e.append(copy.deepcopy(e[0]))
            if mode == 'extra': e.append(dict(id='unknown', status='ok'))
            if mode == 'failed': e[0]['status'] = 'failed'
            if mode == 'null-market': e[0]['markets']['KR'] = None
            if mode == 'optional-nan': e[0]['markets']['KR']['is']['volatility'] = float('nan')
            with self.subTest(mode=mode), self.assertRaises(c.ContractError): c.select_candidate(p, e)

    def test_synthetic_legacy_audit_recomputes_and_detects_tampering(self):
        # In-memory synthetic legacy evidence. Trust anchors are explicitly
        # replaced; this fixture cannot attest to historical market results.
        p = plan(); next_experiment = p.pop('next_experiment')
        p.update(schema_version=1, set_id='2026-11-10_ema_cross', engine_commit=c.LEGACY_ENGINE)
        for candidate in [p['baseline']]+p['variants']:
            candidate['run_id'] = candidate['run_id'].replace('synthetic', 'ema_cross')
        fourth = copy.deepcopy(p['variants'][-1]); fourth.update(run_id=p['set_id']+'__v004', parameters={'n':4}, signal='close > 4'); p['variants'].append(fourth)
        p['selection'] = copy.deepcopy(c.LEGACY_SELECTION); p['evaluation'] = copy.deepcopy(c.LEGACY_EVALUATION)
        mp = copy.deepcopy(p); mp.update(schema_version=2, next_experiment=next_experiment)
        e = entries(mp); selected = c.select_candidate(mp, e); evaluated = c.evaluate_candidate(mp, e, selected['selected_run_id'])
        data = {}
        def put(path, value, raw=False):
            data[path] = value if raw else json.dumps(value).encode()
            return hashlib.sha256(data[path]).hexdigest()
        plan_hash = put('public/plan.json', p); put('private/plan.json', data['public/plan.json'], True)
        index_hash = put('private/results-index-at-selection.json', e); put('private/results/index.json', e)
        events = []
        for candidate, row in zip([p['baseline']]+p['variants'], e):
            rid = row['id']; sha = put('private/results/'+rid+'.json', {'id':rid, 'curves':{}})
            stdout = put('private/logs/'+rid+'.stdout', b'synthetic status only', True)
            stderr = put('private/logs/'+rid+'.stderr', b'', True)
            strategy_hash = put('public/strategies/'+rid+'.toml', b'SYNTHETIC strategy', True)
            start = dict(candidate, event='start', role='baseline' if candidate == p['baseline'] else 'variant', status='running', exit_code=None, engine_commit=p['engine_commit'], data_manifest_sha256=p['data_manifest_sha256'], preregistration_commit=c.LEGACY_PREREG, strategy_sha256=strategy_hash, started_at='2026-11-10T01:00:00+09:00', finished_at=None)
            end = dict(start, event='end', status='ok', exit_code=0, finished_at='2026-11-10T01:00:01+09:00', result_sha256=sha, stdout_sha256=stdout, stderr_sha256=stderr)
            events.extend([start,end])
        event_bytes = b'\n'.join(json.dumps(v).encode() for v in events)
        put('public/attempts.jsonl', event_bytes, True); put('private/attempts.jsonl', event_bytes, True)
        rank = [dict(run_id=r['run_id'], metrics_is=e[next(i for i,v in enumerate(e) if v['id']==r['run_id'])]['markets'], mean_sharpe=r['mean_is_sharpe'], mean_cagr=r['mean_is_cagr'], mean_mdd=r['mean_is_mdd']) for r in selected['ranking']]
        for row in rank: row['metrics_is'] = {m: v['is'] for m,v in row['metrics_is'].items()}
        common = dict(set_id=p['set_id'], selected_run_id=selected['selected_run_id'], holdout_status='exposed', plan_sha256=plan_hash, data_manifest_sha256=p['data_manifest_sha256'], private_results_index_sha256=index_hash, selection_split='IS', oos_used_for_selection=False)
        private_selection = dict(common, criterion=p['selection'], ranked_is_candidates=rank, all_attempts=events[1::2], preregistration_commit=c.LEGACY_PREREG)
        sel_hash = put('private/selection.json', private_selection)
        public_selection = dict(common, private_selection_sha256=sel_hash, selection_rule=p['selection'], all_attempt_ids=[r['id'] for r in e], baseline_run_id=p['baseline']['run_id'], successful_variant_ids=[v['run_id'] for v in p['variants']])
        put('public/selection.json', public_selection)
        candidates = [dict(run_id=r['id'], parameters=v['parameters'], markets=r['markets'], is_mean_sharpe='1', oos_mean_sharpe='1') for v,r in zip([p['baseline']]+p['variants'],e)]
        ev = dict(evaluated, set_id=p['set_id'], status='completed', selected_run_id=selected['selected_run_id'], baseline_run_id=p['baseline']['run_id'], selection_commit=c.LEGACY_SELECTION_COMMIT, preregistration_commit=c.LEGACY_PREREG, engine_commit=p['engine_commit'], data_manifest_sha256=p['data_manifest_sha256'], holdout_status='exposed', all_candidates=candidates)
        ev['next_experiment'] = next_experiment['hypothesis']
        hashes = dict(plan=plan_hash, evaluation=put('private/evaluation.json', ev), private_report=put('private/report.md', b'SYNTHETIC report', True), public_report=put('public/report-toss-completed.md', b'SYNTHETIC report', True))
        original = copy.deepcopy(data)
        def read(path):
            try: return data[str(path)]
            except KeyError: raise c.ContractError('missing synthetic evidence') from None
        with patch.object(c, '_read', side_effect=read), patch.object(c, '_git_blob', side_effect=lambda commit, name: original['public/'+name]), patch.object(c, 'LEGACY_HASHES', hashes), patch.object(c, 'validate_plan', wraps=c.validate_plan) as validate:
            result = c.audit_legacy_ema('public', 'private')
            adapted = validate.call_args_list[0].args[0]
            self.assertNotIn('next_experiment', p)
            self.assertEqual(adapted['next_experiment'], dict(
                hypothesis=ev['next_experiment'],
                reason='Follow-up recorded in the hash-pinned historical evaluation: ' + ev['next_experiment']))
            self.assertEqual(result['status'], 'completed'); self.assertEqual(result['conclusion'], 'accept')
            self.assertEqual(data, original)
            for target in ('private/results/index.json', 'private/logs/'+e[0]['id']+'.stdout', 'private/evaluation.json', 'public/plan.json'):
                data[target] += b' tampered'
                with self.subTest(target=target), self.assertRaises(c.ContractError): c.audit_legacy_ema('public', 'private')
                data[target] = original[target]

    def test_legacy_audit_missing_evidence_is_controlled(self):
        with self.assertRaises(c.ContractError) as caught:
            c.audit_legacy_ema('/nonexistent/synthetic-public', '/nonexistent/synthetic-private')
        self.assertNotIn('synthetic-private', str(caught.exception))

    def test_extreme_finite_decimal_metrics_are_exact_without_context_overflow(self):
        p = plan(); e = entries(p)
        for m in ('US', 'KR'):
            e[1]['markets'][m]['is']['sharpe'] = '1e1000000'
        self.assertEqual(c.select_candidate(p, e)['selected_run_id'], e[1]['id'])

    def test_identical_executable_signals_rejected_despite_different_parameters(self):
        p = plan()
        p['variants'][0]['signal'] = p['baseline']['signal']
        self.assertNotEqual(p['variants'][0]['parameters'], p['baseline']['parameters'])
        with self.assertRaisesRegex(c.ContractError, 'duplicate candidate'):
            c.validate_plan(p)

    def test_normalized_signal_duplicates_ignore_only_executable_syntax_noise(self):
        baseline = 'ema(close, 20) > ema(close, 60)'
        duplicates = [
            ' ema ( close , 20 ) > ema ( close , 60 ) ',
            '((ema((close), (20))) > (ema(close, 60)))',
            'ema(close, 020.00) > ema(close, 60.0)',
        ]
        for signal in duplicates:
            with self.subTest(signal=signal):
                p = plan(); p['baseline']['signal'] = baseline
                p['variants'][0]['signal'] = signal
                with self.assertRaisesRegex(c.ContractError, 'duplicate candidate'):
                    c.validate_plan(p)
        # No arbitrary algebra, ref resolution, commutativity or behavioral
        # equivalence claim: only identical normalized expression trees.
        for signal in ('ema(close, 20) + 0 > ema(close, 60)',
                       'ema(close, 60) < ema(close, 20)',
                       'ema(close, 21) > ema(close, 60)'):
            p = plan(); p['baseline']['signal'] = baseline
            p['variants'][0]['signal'] = signal
            self.assertEqual(c.validate_plan(p), p)

    def test_normalized_signal_validation_preserves_structure_and_string_contents(self):
        p = plan()
        p['baseline']['signal'] = 'close - (2 - 1)'
        p['variants'][0]['signal'] = '(close - 2) - 1'
        p['variants'][1]['signal'] = 'ref("id with spaces")'
        self.assertEqual(c.validate_plan(p), p)
        p['variants'][0]['signal'] = 'ref("idwithspaces")'
        self.assertEqual(c.validate_plan(p), p)
        for signal in ('close >', '(close > 2', 'close > 1 garbage',
                       'close > 1e2', '__import__("os").system("bad")'):
            p['variants'][0]['signal'] = signal
            with self.subTest(signal=signal), self.assertRaises(c.ContractError):
                c.validate_plan(p)

    def test_numeric_parameter_spellings_are_not_distinct_variants(self):
        p = plan()
        p['variants'][0].update(parameters={'n': 1.0}, signal='close > 1')
        with self.assertRaises(c.ContractError): c.validate_plan(p)

    def test_next_experiment_requires_concrete_hypothesis_and_reason(self):
        p = plan()
        del p['next_experiment']
        with self.assertRaises(c.ContractError): c.validate_plan(p)
        for value in (None, '', 'RSI thresholds need study', {},
                      {'hypothesis': 'Test a five-bar momentum filter.'},
                      {'reason': 'The current rule lacks a turnover constraint.'}):
            p = plan(); p['next_experiment'] = value
            with self.subTest(value=value), self.assertRaises(c.ContractError):
                c.validate_plan(p)
        for field in ('hypothesis', 'reason'):
            for value in (None, 123, '', ' ' * 30, 'Short next step',
                          'TODO: write the next experiment here',
                          'TBD ' * 10, '<insert concrete experiment here>',
                          'placeholder for the next hypothesis',
                          'Insert next hypothesis here', 'null ' * 10,
                          'Preregister a new date and new data window before further tuning.'):
                p = plan(); p['next_experiment'][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(c.ContractError):
                    c.validate_plan(p)
        p = plan()
        self.assertEqual(c.validate_plan(p)['next_experiment'], p['next_experiment'])

    def test_reject_invalid_plan_fields(self):
        cases = [('schema_version', 1), ('set_id', '2026-02-30_bad'),
                 ('timezone', 'UTC'), ('markets', ['US']), ('hypothesis', ''),
                 ('tracking_issue', 'https://github.com/evil/sh-quant/issues/30'),
                 ('engine_commit', 'a'*39), ('binary_sha256', 'z'*64),
                 ('cargo_lock_sha256', None), ('data_manifest_sha256', ''),
                 ('holdout_status', 'sealed'), ('variants', [])]
        for key, value in cases:
            with self.subTest(field=key):
                p = plan(); p[key] = value
                with self.assertRaises(c.ContractError): c.validate_plan(p)

    def test_reject_duplicate_candidates_and_invalid_budget(self):
        for change in ('duplicate', 'same_semantics', 'whitespace', 'unsafe', 'budget', 'repairs', 'infinite'):
            p = plan()
            if change == 'duplicate': p['variants'][0]['run_id'] = p['baseline']['run_id']
            if change == 'same_semantics': p['variants'][0].update(parameters={'n': 1}, signal='close > 1')
            if change == 'whitespace': p['variants'][0].update(parameters={'n': 1}, signal=' close  >  1 ')
            if change == 'unsafe': p['variants'][0]['run_id'] += '/bad'
            if change == 'budget': p['budget']['max_attempts'] = 2
            if change == 'repairs': p['budget']['max_repairs'] = 4
            if change == 'infinite': p['budget']['max_wall_minutes'] = float('inf')
            with self.subTest(change=change), self.assertRaises(c.ContractError): c.validate_plan(p)

    def test_valid_plan_and_unknown_policy_rejected(self):
        p = plan()
        self.assertEqual(c.validate_plan(p), p)
        p['machine_policy']['selection'] = 'English prose or eval()'
        with self.assertRaises(c.ContractError):
            c.validate_plan(p)


if __name__ == '__main__':
    unittest.main()
