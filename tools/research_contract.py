"""Pure, fail-closed preregistered research policy (#30).

Returned ranking/evaluation evidence is PRIVATE and must not be printed publicly.
"""


class ContractError(ValueError):
    """Invalid research contract; messages never include provider payloads."""


import hashlib
from pathlib import Path
import subprocess


def _read(path):
    try:
        return Path(path).read_bytes()
    except OSError:
        raise ContractError('missing audit evidence') from None


LEGACY_ENGINE = '9bbe70c5e501f1b536dc8780232c5f5c37a5c66f'
LEGACY_PREREG = 'd2b16faf3b2af7446247c5f8a77b968f084e182d'
LEGACY_SELECTION_COMMIT = '05ca9c5a844ff7a80c3d265d987e8711f509d411'
LEGACY_HASHES = dict(
    plan='dd6b25cb296b70737702259df0ac35fe68995a7cf8838db0712c360444f68216',
    evaluation='3b504d52dc1c23b0b6b10c99bb8cb7955d34f8b4787fcc1b32ae477cc92b1ad2',
    private_report='10e08ec5be812742939de6efe2e77104abf3a45bf77313eb7728e6d1c953d135',
    public_report='3a5cafcaf4b9e70baa06d738fa560160e39c95ee74ae2f39bd7dc0f649459d76')
LEGACY_SELECTION = dict(split='IS', objective='maximize arithmetic mean of US and KR IS sharpe as stored by engine (4 decimals)', tie_break='then maximize mean IS cagr, then maximize mean IS mdd (less negative), then baseline first, then lexicographic run_id; exact Decimal comparisons of stored values')
LEGACY_EVALUATION = dict(
    benchmark='engine available-asset equal-weight buy-and-hold using same provider adjusted-price closes',
    metrics=['cagr', 'sharpe', 'mdd', 'excess_cagr'],
    accept_criteria='selected OOS sharpe>0 in BOTH markets AND mean OOS excess_cagr>=0 AND mean selected OOS mdd>=mean baseline OOS mdd',
    reject_criteria='if not accept: selected OOS excess_cagr<0 in BOTH markets AND mean selected OOS sharpe<=mean baseline OOS sharpe',
    defer_criteria='all other successful research outcomes; never operational failure',
    precedence='accept then reject then defer; no parameter changes after observation')


def _sha(blob):
    return hashlib.sha256(blob).hexdigest()


def _decode(blob):
    try:
        return json.loads(blob)
    except (ValueError, UnicodeError):
        raise ContractError('invalid audit JSON') from None


def _git_blob(commit, name):
    root = Path(__file__).resolve().parents[1]
    path = name if '/' in name else 'research/2026-11-10_ema_cross/' + name
    try:
        return subprocess.run(['git', 'show', commit+':'+path], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    except (OSError, subprocess.CalledProcessError):
        raise ContractError('missing historical reference') from None


def audit_legacy_ema(public_dir, private_dir):
    """Read-only, fail-closed audit. Returns publication-safe metadata only.

    Does not migrate plans, execute strategies, or certify an unseen holdout.
    Git objects and fixed hashes are historical trust anchors, not fresh runs.
    """
    try:
        return _audit_legacy_ema(Path(public_dir), Path(private_dir))
    except ContractError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OSError):
        raise ContractError('malformed legacy evidence') from None


def _audit_legacy_ema(public, private):
    raw_plan = _read(public/'plan.json')
    _require(_sha(raw_plan) == LEGACY_HASHES['plan'], 'legacy plan hash mismatch')
    _require(raw_plan == _read(private/'plan.json') == _git_blob(LEGACY_PREREG, 'plan.json'), 'historical plan mismatch')
    plan = _decode(raw_plan)
    _require(plan['schema_version'] == 1 and plan['set_id'] == '2026-11-10_ema_cross' and plan['engine_commit'] == LEGACY_ENGINE)
    _require(plan['selection'] == LEGACY_SELECTION and plan['evaluation'] == LEGACY_EVALUATION, 'unsupported legacy policy')
    machine = dict(plan, schema_version=2, machine_policy=dict(POLICY))
    validate_plan(machine)
    candidates = [plan['baseline']] + plan['variants']
    _require(len(candidates) == 4, 'legacy trial count mismatch')
    ids = [v['run_id'] for v in candidates]
    raw_selection = _read(public/'selection.json')
    _require(raw_selection == _git_blob(LEGACY_SELECTION_COMMIT, 'selection.json'), 'historical selection mismatch')
    selection = _decode(raw_selection)
    private_raw_selection = _read(private/'selection.json')
    _require(_sha(private_raw_selection) == selection['private_selection_sha256'], 'selection hash mismatch')
    private_selection = _decode(private_raw_selection)
    for claim in (selection, private_selection):
        _require(claim['set_id'] == plan['set_id'] and claim['plan_sha256'] == _sha(raw_plan) and claim['data_manifest_sha256'] == plan['data_manifest_sha256'])
        _require(claim['selection_split'] == 'IS' and claim['oos_used_for_selection'] is False and claim['holdout_status'] == 'exposed')
    _require(selection['selection_rule'] == private_selection['criterion'] == LEGACY_SELECTION, 'legacy selection policy mismatch')
    _require(selection['all_attempt_ids'] == ids and selection['baseline_run_id'] == ids[0] and selection['successful_variant_ids'] == ids[1:])
    _require(private_selection['preregistration_commit'] == LEGACY_PREREG)
    raw_index = _read(private/'results-index-at-selection.json')
    _require(_sha(raw_index) == selection['private_results_index_sha256'] == private_selection['private_results_index_sha256'], 'selection index hash mismatch')
    entries = _decode(raw_index)
    rows = _entries(machine, entries)
    current = _decode(_read(private/'results/index.json'))
    _entries(machine, current)
    def without_lessons(values):
        return {r['id']: {k:v for k,v in r.items() if k != 'lesson'} for r in values}
    _require(without_lessons(entries) == without_lessons(current), 'index changed beyond lessons')
    raw_events = _read(public/'attempts.jsonl')
    _require(raw_events == _read(private/'attempts.jsonl') == _git_blob(LEGACY_SELECTION_COMMIT, 'attempts.jsonl'), 'attempt evidence mismatch')
    events = [_decode(line) for line in raw_events.splitlines()]
    _require(len(events) == 8, 'legacy event count mismatch')
    for candidate, start, end in zip(candidates, events[::2], events[1::2]):
        rid = candidate['run_id']
        for event in (start, end):
            _require(all(event[k] == candidate[k] for k in ('run_id', 'parameters', 'signal')))
            _require(event['engine_commit'] == LEGACY_ENGINE and event['preregistration_commit'] == LEGACY_PREREG and event['data_manifest_sha256'] == plan['data_manifest_sha256'])
            _require(event['role'] == ('baseline' if rid == ids[0] else 'variant'))
        _require(start['event'] == 'start' and start['status'] == 'running' and start['exit_code'] is None)
        _require(end['event'] == 'end' and end['status'] == 'ok' and type(end['exit_code']) is int and end['exit_code'] == 0)
        _require(start['started_at'] == end['started_at'] and datetime.datetime.fromisoformat(start['started_at']) <= datetime.datetime.fromisoformat(end['finished_at']))
        _require(start['strategy_sha256'] == end['strategy_sha256'] == _sha(_git_blob(LEGACY_PREREG, 'strategies/'+rid+'.toml')), 'strategy hash mismatch')
        result_raw = _read(private/'results'/(rid+'.json'))
        _require(_sha(result_raw) == end['result_sha256'] and _decode(result_raw)['id'] == rid, 'result hash mismatch')
        for stream in ('stdout', 'stderr'):
            _require(_sha(_read(private/'logs'/(rid+'.'+stream))) == end[stream+'_sha256'], 'log hash mismatch')
    _require(private_selection['all_attempts'] == events[1::2], 'selection attempts mismatch')
    selected = select_candidate(machine, entries)
    rid = selected['selected_run_id']
    _require(selection['selected_run_id'] == private_selection['selected_run_id'] == rid, 'selection claim mismatch')
    expected_rank = []
    for ranking in selected['ranking']:
        row = rows[ranking['run_id']]
        expected_rank.append(dict(run_id=row['id'], metrics_is={m:row['markets'][m]['is'] for m in ('US', 'KR')}, mean_sharpe=ranking['mean_is_sharpe'], mean_cagr=ranking['mean_is_cagr'], mean_mdd=ranking['mean_is_mdd']))
    _require(private_selection['ranked_is_candidates'] == expected_rank, 'ranking evidence mismatch')
    raw_evaluation = _read(private/'evaluation.json')
    _require(_sha(raw_evaluation) == LEGACY_HASHES['evaluation'], 'evaluation hash mismatch')
    evaluation = _decode(raw_evaluation)
    computed = evaluate_candidate(machine, entries, rid)
    _require(evaluation['status'] == 'completed' and evaluation['conclusion'] == computed['conclusion'] and evaluation['criteria_evidence'] == computed['criteria_evidence'], 'evaluation claim mismatch')
    _require(evaluation['selected_run_id'] == rid and evaluation['baseline_run_id'] == ids[0] and evaluation['set_id'] == plan['set_id'])
    _require(evaluation['selection_commit'] == LEGACY_SELECTION_COMMIT and evaluation['preregistration_commit'] == LEGACY_PREREG and evaluation['engine_commit'] == LEGACY_ENGINE)
    _require(evaluation['holdout_status'] == 'exposed' and evaluation['data_manifest_sha256'] == plan['data_manifest_sha256'])
    expected_candidates = []
    for candidate in candidates:
        row = rows[candidate['run_id']]
        expected_candidates.append(dict(run_id=row['id'], parameters=candidate['parameters'], markets=row['markets'], is_mean_sharpe=str(_mean([row['markets'][m]['is']['sharpe'] for m in ('US', 'KR')])), oos_mean_sharpe=str(_mean([row['markets'][m]['oos']['sharpe'] for m in ('US', 'KR')]))))
    _require(evaluation['all_candidates'] == expected_candidates, 'evaluation candidates mismatch')
    _require(_sha(_read(private/'report.md')) == LEGACY_HASHES['private_report'], 'private report hash mismatch')
    _require(_sha(_read(public/'report-toss-completed.md')) == LEGACY_HASHES['public_report'], 'public report hash mismatch')
    return dict(status='completed', conclusion=computed['conclusion'], selected_run_id=rid, plan_sha256=_sha(raw_plan), selection_sha256=_sha(raw_selection), evaluation_sha256=_sha(raw_evaluation))


POLICY = {'selection': 'mean_is_sharpe_v1', 'evaluation': 'sharpe_excess_mdd_v1'}


import datetime
import json
import re
from decimal import Decimal, InvalidOperation, localcontext


def _require(condition, message='invalid research contract'):
    if not condition:
        raise ContractError(message)


def _number(value):
    _require(type(value) in (str, int, float, Decimal), 'invalid finite metric')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ContractError('invalid finite metric') from None
    _require(result.is_finite(), 'invalid finite metric')
    return result


def _json_finite(value):
    if isinstance(value, dict):
        _require(all(isinstance(k, str) for k in value))
        for v in value.values(): _json_finite(v)
    elif isinstance(value, list):
        for v in value: _json_finite(v)
    elif isinstance(value, float):
        _number(value)
    else:
        _require(value is None or type(value) in (str, bool, int))


def _semantic_parameters(value):
    if isinstance(value, dict):
        return ('object', tuple((k, _semantic_parameters(v)) for k, v in sorted(value.items())))
    if isinstance(value, list):
        return ('array', tuple(_semantic_parameters(v) for v in value))
    if type(value) in (int, float):
        return ('number', _number(value))
    return (type(value).__name__, value)


def validate_plan(plan):
    _require(isinstance(plan, dict))
    _json_finite(plan)
    _require(plan.get('machine_policy') == POLICY, 'unsupported machine policy')
    _require(type(plan.get('schema_version')) is int and plan['schema_version'] == 2)
    sid = plan.get('set_id')
    _require(isinstance(sid, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}_[a-z0-9][a-z0-9_-]*', sid))
    try: datetime.date.fromisoformat(sid[:10])
    except ValueError: raise ContractError('invalid set date') from None
    _require(plan.get('timezone') == 'Asia/Seoul' and plan.get('markets') in (['US', 'KR'], ['KR', 'US']))
    _require(plan.get('holdout_status') == 'exposed')
    _require(isinstance(plan.get('hypothesis'), str) and plan['hypothesis'].strip())
    issue = plan.get('tracking_issue')
    _require(isinstance(issue, str) and re.fullmatch(r'https://github\.com/seanjeonn/sh-quant/issues/[1-9][0-9]*', issue))
    for field, length in [('engine_commit', 40), ('cargo_lock_sha256', 64), ('binary_sha256', 64), ('data_manifest_sha256', 64)]:
        value = plan.get(field)
        _require(isinstance(value, str) and re.fullmatch('[0-9a-fA-F]{'+str(length)+'}', value))
    variants = plan.get('variants')
    _require(isinstance(variants, list) and len(variants) >= 2)
    candidates = [plan.get('baseline')] + variants
    ids, semantics = set(), set()
    for candidate in candidates:
        _require(isinstance(candidate, dict))
        rid, params, signal = (candidate.get(k) for k in ('run_id', 'parameters', 'signal'))
        _require(isinstance(rid, str) and re.fullmatch(re.escape(sid)+r'__[A-Za-z0-9][A-Za-z0-9_-]*', rid))
        _require(rid not in ids)
        ids.add(rid)
        _require(isinstance(params, dict) and isinstance(signal, str) and signal.strip())
        signature = (_semantic_parameters(params), re.sub(r'\s+', '', signal))
        _require(signature not in semantics, 'duplicate candidate semantics')
        semantics.add(signature)
    budget = plan.get('budget')
    _require(isinstance(budget, dict))
    for field, low, high in [('max_attempts', len(candidates), 12), ('max_wall_minutes', 1, 120), ('max_repairs', 0, 3)]:
        value = budget.get(field)
        _require(type(value) is int and low <= value <= high, 'invalid execution budget')
    _require(budget['max_repairs'] <= budget['max_attempts'])
    return plan


def _mean(values):
    # Enough precision for an exact sum and division by two, independent of
    # the caller's decimal context (stored decimal strings are authoritative).
    values = [_number(v) for v in values]
    precision = max(v.adjusted() for v in values) - min(v.as_tuple().exponent for v in values) + 4
    with localcontext() as ctx:
        ctx.prec = max(precision, 28)
        ctx.Emax = max(ctx.Emax, max(v.adjusted() for v in values) + 4)
        ctx.Emin = min(ctx.Emin, min(v.as_tuple().exponent for v in values) - 4)
        return (values[0] + values[1]) / Decimal(2)


def _entries(plan, entries):
    validate_plan(plan)
    _require(isinstance(entries, list), 'invalid result entries')
    expected = {v['run_id'] for v in [plan['baseline']] + plan['variants']}
    found = {}
    for row in entries:
        _require(isinstance(row, dict), 'invalid result entry')
        rid = row.get('id')
        _require(isinstance(rid, str) and rid in expected and rid not in found, 'candidate coverage mismatch')
        _require(row.get('status') == 'ok', 'unsuccessful candidate')
        markets = row.get('markets')
        _require(isinstance(markets, dict) and set(markets) == {'US', 'KR'}, 'invalid result markets')
        for market in markets.values():
            _require(isinstance(market, dict), 'invalid market metrics')
            for split in ('is', 'oos'):
                metrics = market.get(split)
                _require(isinstance(metrics, dict), 'missing result metrics')
                for value in metrics.values():
                    _number(value)
                for name in ('sharpe', 'cagr', 'mdd', 'excess_cagr'):
                    _number(metrics.get(name))
        found[rid] = row
    _require(set(found) == expected, 'candidate coverage mismatch')
    return found


def select_candidate(plan, entries):
    """Return PRIVATE exact IS-only ranking; never rank on OOS."""
    rows = _entries(plan, entries)
    ranked = []
    for rid, row in rows.items():
        means = [_mean([row['markets'][m]['is'][metric] for m in ('US', 'KR')]) for metric in ('sharpe', 'cagr', 'mdd')]
        ranked.append((rid, means))
    # Decimal.copy_negate does not round under an ambient decimal context.
    ranked.sort(key=lambda item: tuple(v.copy_negate() for v in item[1]) + (item[0] != plan['baseline']['run_id'], item[0]))
    return dict(selected_run_id=ranked[0][0], criterion=POLICY['selection'],
                ranking=[dict(run_id=rid, **dict(zip(('mean_is_sharpe', 'mean_is_cagr', 'mean_is_mdd'), map(str, means)))) for rid, means in ranked])


def evaluate_candidate(plan, entries, selected_run_id):
    """Return PRIVATE preregistered OOS evidence, not operational conclusions."""
    rows = _entries(plan, entries)
    _require(select_candidate(plan, entries)['selected_run_id'] == selected_run_id, 'selected candidate claim mismatch')
    selected, baseline = rows[selected_run_id], rows[plan['baseline']['run_id']]
    def mean(row, metric):
        return _mean([row['markets'][m]['oos'][metric] for m in ('US', 'KR')])
    positive = all(_number(selected['markets'][m]['oos']['sharpe']) > 0 for m in ('US', 'KR'))
    negative = all(_number(selected['markets'][m]['oos']['excess_cagr']) < 0 for m in ('US', 'KR'))
    excess, mdd, base_mdd = mean(selected, 'excess_cagr'), mean(selected, 'mdd'), mean(baseline, 'mdd')
    sharpe, base_sharpe = mean(selected, 'sharpe'), mean(baseline, 'sharpe')
    accept = positive and excess >= 0 and mdd >= base_mdd
    reject = not accept and negative and sharpe <= base_sharpe
    evidence = dict(selected_oos_sharpe_positive_both=positive, selected_mean_oos_excess_cagr=str(excess),
                    selected_mean_oos_mdd=str(mdd), baseline_mean_oos_mdd=str(base_mdd),
                    selected_oos_excess_negative_both=negative, selected_mean_oos_sharpe=str(sharpe),
                    baseline_mean_oos_sharpe=str(base_sharpe), accept=accept, reject=reject)
    return dict(conclusion='accept' if accept else 'reject' if reject else 'defer',
                criterion=POLICY['evaluation'], criteria_evidence=evidence)
