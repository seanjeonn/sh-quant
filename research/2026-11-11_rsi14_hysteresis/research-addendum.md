# RSI14 hysteresis — qualitative research addendum

Tracking issue: #37. Set: `2026-11-11_rsi14_hysteresis`.

## Hypothesis and preregistration

The first executable unfinished backlog hypothesis was RSI14 mean reversion. The prior completed EMA set proposed these same threshold pairs before this set's scores were inspected. No legacy EMA trial was repeated.

Baseline: `latch(rsi(close, 14) < 30, rsi(close, 14) > 70)`.
Variant v001: entry below 25, exit above 75.
Variant v002: entry below 35, exit above 65.

All candidates use the existing next-bar position lag, costs, weighting and split. The bounded plan allowed three attempts, sixty minutes and no repairs; no score-driven engine or policy changes were made. The supervisor's already frozen snapshot was the only input. No market acquisition or credential access was performed by this research session.

Private plan SHA-256: `7676046c87e4bb3205ffd1b7cbf0f920c2b09722777ffda5112f3de06571a54e`.
Plan checkpoint commit: `ee26b99` (exact remote descriptor gate passed before the first trial).
Selection checkpoint commit: `624f803` (exact remote descriptor gate passed before evaluation).
Engine revision: `1bfb36c282821a3c8d6b00a589e819a2f11753e4`.
Frozen manifest SHA-256: `88a848e6a132bc866dea48779d33e7f61c0985c4d8d37dfbd1960bc87bf0c894`.

## Actual evidence and conclusion

Three sequential trials succeeded once each; no failed trial, repair, or successful-ID rerun. The private report retains all start/child/end records and actual result/log hashes. Runner verification recomputed the declared policies and validated immutable evidence.

The preregistered `mean_is_sharpe_v1` ordering was baseline (30/70), then v002 (35/65), then v001 (25/75). Selection used US/KR equal-weight IS Sharpe means, with the versioned tie-breaks; OOS did not determine ranking. Narrower or wider thresholds did not improve the declared development objective over baseline. This finite comparison does not establish global parameter robustness.

Final machine conclusion: `reject`, under `sharpe_excess_mdd_v1`. The selected baseline had positive OOS Sharpe in both markets but negative OOS excess CAGR against same-data buy-and-hold in both. Since the selected candidate is the baseline, its OOS mean Sharpe equals baseline rather than improving on it; the policy's non-improvement condition includes equality. The accept condition fails and the reject condition holds. This is a completed negative research result, not a data/execution blocker or a trading recommendation.

The stricter variant's exposed OOS observations do not authorize replacing the IS-selected baseline. No further RSI thresholds were tried after observing outcomes.

Private evaluation SHA-256: `30629cf6bf8e6af3ed43bfad93b6580d18c1259a92526a082050e39bbf327d55`.
Private numeric report SHA-256: `fd54e59fdc3a9f99262082093bc0a08bed4bf66d1cc5bd74bfcbd1d2cffd3a5f`.
Actual per-candidate IS/OOS evidence and lessons were inspected privately. Raw quotes, numerical performance, curves and detailed local paths are not published. `publication.json` is the supervisor-rendered deterministic descriptor copied byte-for-byte, not an agent-authored replacement summary.

## Limitations and next experiment

OOS is jointly computed/stored and historically exposed, not sealed or independent validation. Prior EMA/older OOS influenced family selection. Toss provider-defined adjusted-price returns are not dividend-reinvested total returns. Current fixed-universe survivorship bias and uncertified exchange-calendar/corporate-action completeness remain. No significance or multiple-testing correction is claimed. Related limitations remain tracked in #28, #13, #16 and #24; these issues are not closed by this study.

Next hypothesis, preregistered before these trials: Bollinger-band lower-entry mean reversion with a twenty-day centerline exit may normalize oversold entry across volatility regimes better than fixed RSI thresholds. Compare band widths 2.0 standard deviations (baseline), 1.5 and 2.5, on a future separately registered set. Reason: next executable backlog item and a different oversold measurement, not extra RSI tuning on observed OOS. Deferred follow-up: #38. No next-set trial was executed today.

## Validation and integration boundary

`cargo test --locked --offline`: twenty tests passed, one intentional process-holder helper ignored. Python unittest discovery: 129 tests passed. These offline regression tests are separate from the three actual market-data strategy trials. `research_set verify` returned completed/reject after both remote checkpoints. Source, tools, Cargo, dashboard, old research and public results were not changed.

The working research branch is `research/2026-11-11_daily`, stacked on `feat/33-investops-supervisor`. Runner completion and final remote publication verification are distinct gates. Main merge/auto-merge, manual deployment/release, account/order APIs, purchases and live trading were not performed. No scheduler configuration was changed in this research session.
