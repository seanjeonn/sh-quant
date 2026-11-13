# Bollinger reversion — qualitative research addendum

Tracking issue: #53. Approved early catch-up context: #52. Set: `2026-11-13_bollinger_reversion`.

## Hypothesis and preregistration

The first executable unfinished backlog item was twenty-day Bollinger lower-band mean reversion, with centerline exit. Prior completed EMA/defer and RSI14/reject lessons were reviewed read-only. The prior RSI plan and #38 named widths 2.0, 1.5 and 2.5 before this set. No legacy EMA set was rerun.

Baseline: `latch(close < sma(close, 20) - 2.0 * std(close, 20), close >= sma(close, 20))`.
Variant v001 uses width 1.5; v002 uses width 2.5. The lookback and exit remain identical. These are different executable signals, not metadata-only variants. Existing next-bar lag, costs, weighting, splits and engine policies were unchanged.

The private schema2 plan allowed three sequential attempts, sixty minutes and zero repairs, subordinate to the supervisor scope. Only the supervisor's already frozen snapshot was used; this session performed no acquisition or credential access. No source, tools, Cargo, config, engine, dashboard, old research or public results were edited.

Private plan SHA-256: `1affe2bc1b17aaca7ea481820a1be056d1248a21faf9851a4f14578660625567`.
Plan checkpoint commit: `e1961ab2fb4e081baa2a61d0dfd7b01ca6bab813`.
Selection checkpoint commit: `e2a3e7bce5395e4ebc123b1a7d6574bb5eb1548e`.
Engine revision: `bc99433be274521def588c6e23ea655875b73193`.
Frozen manifest SHA-256: `97b07af95a2b065bda084d27c4137c711659b5a9ac195bb7da8f929e2e913323`.

Both checkpoints read exact remote commit/path blobs and branch state before their next phase. No trial preceded the plan gate; no evaluation preceded the selection gate.

## Actual evidence and conclusion

All three preregistered candidates succeeded once, sequentially, with exit code zero. There were no failed strategy trials, repairs, timeouts or successful-ID reruns. Immutable start/child/end records, actual result/index/detail/log hashes and all input fingerprints were validated by Runner.verify.

The `mean_is_sharpe_v1` IS ordering was v002 (2.5), baseline (2.0), v001 (1.5). Selection maximized the equal-weight US/KR IS Sharpe mean with the fixed tie-breaks, not OOS. The wider band improved the declared development objective, whereas the narrower band worsened it. This finite comparison does not establish a global optimum or statistical robustness.

Final machine conclusion: `defer`, under `sharpe_excess_mdd_v1`. The selected candidate had positive OOS Sharpe in both markets and less severe mean OOS drawdown than baseline, but negative OOS excess CAGR relative to same-data buy-and-hold in both markets. Acceptance therefore failed. Its mean OOS Sharpe improved over baseline, so the policy's rejection condition also failed. The remaining successful outcome is defer. This is a supported research conclusion, not operational blockage, strategy adoption or trading advice.

Private numeric report SHA-256: `0283b9a2b40e15b19a8cac5c21ad9616251d31d61ad8b6bd311a1ff435c4c06b`.
Private evaluation SHA-256: `13d42f230f8a563e0cf94a4798fc27fa9fef7aecd0e13239fb6007676c9c904a`.

Actual per-candidate market metrics, selection, evaluation and lessons were inspected privately. Raw quotes, numeric performance, curves and detailed local paths remain outside Git. `publication.json` is the exact supervisor-rendered deterministic safe JSON, copied byte-for-byte; this addendum is separate qualitative interpretation, not a replacement descriptor. Runner completion and independently verified remote publication are separate gates.

## Limitations and next experiment

Historical OOS influenced family selection and is jointly computed/stored for every trial. It is exposed, not an untouched or independent holdout. Toss provider-defined adjusted-price returns are not dividend-reinvested total returns. Fixed-universe survivorship bias, uncertified exchange-calendar/corporate-action completeness, finite parameter sensitivity and lack of significance/multiple-testing validation remain. Existing follow-ups #28, #13 and #16 are not resolved by this set.

The next experiment was preregistered before these trials: positive twelve-month momentum excluding the most recent month, `lag(close, 21) > lag(close, 252)`, with adjacent horizon variants 231 and 273 and the same 21-day exclusion. Reason: next executable backlog family and a trend-continuation contrast, rather than retuning band widths on observed OOS. Deferred follow-up: #54, originating from #53. No next-set trial was executed today.

## Validation and integration boundary

`cargo test --locked --offline`: twenty tests passed, one intentional process-holder helper ignored. Python unittest discovery: 145 tests passed; synthetic negative-test diagnostics are not real-data failures or research results. Runner.verify returned completed/defer with three actual market-data trials after both remote checkpoints. CLI regression tests and research evidence verification are distinct.

Research branch: `research/2026-11-13_daily`, stacked on pinned core branch `fix/48-supervisor-start-recovery`. Publication is through an open PR against that core branch, not main. No main merge, auto-merge, deployment/release, account/order API, live trading or scheduler change was performed by this session. Issue #53 remains open pending the normal integration workflow.
