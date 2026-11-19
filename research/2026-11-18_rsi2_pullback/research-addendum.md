# Trend-filtered RSI(2) pullback — qualitative research addendum

Tracking #94; source #88. Set `2026-11-18_rsi2_pullback`.

## Hypothesis and preregistration

Buy short-term oversold pullbacks only above the 200-day simple average, then exit on RSI recovery above 50 or loss of the long-term average. Baseline `latch(close > sma(close, 200) and rsi(close, 2) < 10, rsi(close, 2) > 50 or close < sma(close, 200))`; v001 changes entry threshold to 5, v002 to 15. Trend window, RSI window and exit conditions are fixed. Existing next-bar execution, costs, weighting, splits, engine and policies are unchanged.

Reviewed prior EMA/defer, RSI14/reject, Bollinger/defer, momentum/reject and Donchian/defer lessons, current approved issues/comments and open PRs. MACD #85/PR89 and capped risk sizing #90/PR92 already cover the preceding unchecked backlog items, so neither was repeated. Source #88 specified today's family and thresholds before today's scores. Earlier family conclusions informed selection of this experiment; reused historical OOS is exposed, not independent validation.

Private schema2 plan bounded three sequential attempts, zero repairs and sixty minutes, subordinate to the supplied unchanged stable supervisor-scope pointer. Only the supervisor's already frozen snapshot was used. No acquisition or credential access was performed by this session.

Private plan SHA-256: `0eede55af95da3b4ea50ab2e12fbfb435f12686a0b79953745c51ae06c5b6c96`.
Plan checkpoint: `53cf6f6b76be27cdfa842c2257d53a288cf9a86e`.
Selection checkpoint: `2643ccc3df7fd90b2967f9dbf932186ce848f605`.
Engine revision: `06a6b6c45e8f4ade6e5a99fa785b94b3aa9bb135`.
Frozen manifest SHA-256: `85327359d6467ab2674ca61faf961c0a69e055f4e2079b66a2ee20af73e0a186`.

Exact remote descriptor/commit/branch gates preceded trials and evaluation respectively. Both checkpoint commits remain ancestors; no rebase, reset or force push was performed.

## Actual evidence and conclusion

Three preregistered candidates succeeded once each, sequentially, with exit code zero and no timeout, failed trial, repair or successful-ID rerun. Runner.verify returned completed/defer after checking immutable attempts, result/index/detail/log hashes and machine recomputation. Registered worktree, plan source, stable supervisor scope, manifest and binary paths/hashes and engine revision were independently compared with the supplied supervisor context; source pins and frozen CSV hashes were also checked before initialization.

IS-only ranking under `mean_is_sharpe_v1`: v001 (5), baseline (10), v002 (15). Stricter entry improved the declared development objective over baseline; looser entry reduced it. This finite edge selection does not establish a global optimum or robustness. Candidates, selection rule and evaluation policy were not changed after observing OOS.

Fixed `sharpe_excess_mdd_v1` conclusion: `defer`. All candidates had positive OOS Sharpe but negative excess CAGR versus same-data buy-and-hold in both markets. The selected candidate improved mean OOS Sharpe and had less severe mean drawdown than baseline. Negative mean excess CAGR prevents acceptance; improved mean Sharpe prevents the policy's rejection condition. Sparse exposure and missed benchmark participation remain important limitations, not a license for extra trials or live adoption.

Private numeric report SHA-256: `e5f149f742ac81f92e006023c6f12c14242e99ac0b3e99bc27fa90140a0265c5`.
Private evaluation SHA-256: `88569182b4c51c6c58eab61c44c1fc7cb760caf93b306c8d3fa240c6ebaf59e9`.
Private lessons SHA-256: `761a25ee06e9ed844822b48443d85877fdd3065022eceeced5f6b83b4ce47493`.

Private candidate numeric evidence, evaluation and lessons were inspected. Raw prices, numerical performance, curves and detailed local paths stay outside Git. `publication.json` is copied byte-for-byte from the deterministic descriptor persisted by the exact supplied supervisor publication command, not an agent-authored replacement summary. Runner completion and independently verified remote publication are separate gates.

## Limitations and next experiment

Historical OOS is jointly computed and stored, exposed and reused, not untouched or sealed. Provider-defined adjusted-price returns are not dividend-reinvested total returns. Current-selected equity/ETF membership is non-PIT with survivorship bias; delisting/suspension coverage, calendar completeness and corporate actions remain uncertified. Incremental input prefixes retain earlier vintages and do not certify corrections outside the overlap. No significance or multiple-testing robustness is claimed. Existing #13, #28, #16 and #74 track these limitations.

Next experiment, preregistered before trials: `hold(volume > 2 * sma(volume, 20) and close > open, 5)`, comparing volume multipliers 1.5 and 2.5 with the same five-bar hold. Reason: next executable backlog family and a volume-confirmed persistence contrast to pullback reversion, rather than further tuning on exposed OOS. Existing hold semantics refresh exposure on repeated triggers; this is not a guarantee of independent non-overlapping trades. Follow-up proposal #95 records deferred scope from origin #94. No volume strategy trial was executed.

## Validation and integration boundary

Rust tests: 30 passed, one intentional process-holder helper ignored. Initial full Python test command reached its 180-second command timeout before producing a final summary; its partial log is retained. A separately logged second invocation completed all 246 tests successfully in 210.087 seconds. No test code was changed. Synthetic regression tests do not replace actual native market-data evidence verification. Diff whitespace checks passed before publication.

Only this set's research artifacts are changed; shared backlog, source, tools, Cargo, config, dashboard, older research/results and other profiles are unchanged. Known independent ledger/supervisor issues #91/#93 are not repaired or hidden inside research. Tracking #94 stays open pending normal integration; PR creation does not close it. No main merge, auto-merge, deployment/release, scheduler changes, purchases, live trading or account/order APIs were performed.
