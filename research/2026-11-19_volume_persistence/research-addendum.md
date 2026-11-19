# Volume-confirmed five-bar persistence — qualitative research addendum

Tracking #101; source #95; prior #94 / PR #96. Set `2026-11-19_volume_persistence`.

## Hypothesis and preregistration

A bullish daily candle with volume above its twenty-bar average may signal continuation captured by five-bar exposure. Baseline `hold(volume > 2 * sma(volume, 20) and close > open, 5)`; v001 changes the volume multiplier to 1.5, v002 to 2.5. The rolling volume mean includes the signal bar. Existing hold refreshes exposure on repeated triggers; these are not independent non-overlapping five-day trades. Next-bar execution, engine, costs, weighting, splits and policies are unchanged.

Reviewed backlog, prior EMA/defer, RSI14/reject, Bollinger/defer, momentum/reject, Donchian/defer, MACD/reject, risk-sizing/defer and RSI2/defer lessons, current issues/comments and open PRs. MACD #85/PR89, sizing #90/PR92 and RSI2 #94/PR96 already covered the preceding unchecked entries in the pinned backlog, so none was repeated. Source #95 specified today's exact signals before today's scores. Earlier exposed OOS informed the family transition, not a claim of independent validation.

Private schema2 plan bounded three sequential attempts, zero repairs and sixty minutes, subordinate to the supplied unchanged stable supervisor-scope pointer. Only the supervisor's already frozen snapshot was used. This session performed no data acquisition or credential reads. The tracking feature issue preceded plan creation and trials.

Private plan SHA-256: `63e23ec05be1bb5ee3996aad555f28d90c43800e233b794ab87742fc2fb6516a`.
Plan checkpoint: `3d262903425061ca14fb86354dcc4a4bfc6e148e`.
Selection checkpoint: `21cd01533cdf06799184de5b79d7bb21ff12d453`.
Engine revision: `06a6b6c45e8f4ade6e5a99fa785b94b3aa9bb135`.
Frozen manifest SHA-256: `876d5e0ce900b00ddce086fe9f4834ea1e196afa604e4b0dc5ec31876b5c5b9e`.

Exact remote commit/path descriptor gates preceded trials and evaluation respectively. Checkpoint ancestry is preserved without rebase, reset or force push.

## Actual evidence and conclusion

All three preregistered candidates succeeded sequentially once each, exit code zero, with no timeout, failed trial, repair or successful-ID rerun. Runner.verify returned completed/reject and validated immutable attempts, result/index/detail/log hashes plus selection, evaluation, report and lessons. Registered worktree, private plan source, scope pointer/target, binary and manifest paths/hashes and engine revision were independently compared with supplied context. Source fingerprints, lockfile, catalog and frozen CSV hashes were checked. The exact supplied supervisor publication command independently validated bound provenance before rendering deterministic publication bytes.

IS-only ranking under `mean_is_sharpe_v1`: baseline (2), v002 (2.5), v001 (1.5). Neither variant improved the declared development objective over baseline. This is a finite nonmonotonic threshold comparison, not a global optimum or robustness certificate. No candidate, ranking criterion or evaluation policy was changed using OOS.

Fixed `sharpe_excess_mdd_v1` conclusion: `reject`. Every candidate had positive OOS Sharpe but negative excess CAGR against same-data buy-and-hold in both markets. Baseline was selected; selected mean OOS Sharpe and MDD therefore equal baseline by identity. Negative excess in both markets plus mean Sharpe no better than baseline satisfies the fixed rejection rule. This supported negative research conclusion is not an execution blocker, an adoption recommendation or evidence that every volume strategy fails. Intermittent exposure missed benchmark participation under the fixed comparison.

Private numeric report SHA-256: `f262e62c803e7aba1c6311b2b9a58ee1270f9d3a47e60b1eac20bbb106f3662b`.
Private evaluation SHA-256: `37b188c396fc9bc3aea1c3392b24301e7fe7448941075795c7aa5a635a5d2a13`.
Private lessons SHA-256: `dc3c6a9f247adc5ee573acf1e0b734b8d8bb87b66495938ed1620525da10954c`.

Actual private report and every candidate's IS/OOS metrics and lessons were inspected programmatically, including finite numeric fields, exact machine recomputation and qualitative observations. A supplemental inspection helper initially confused the scope-target hash with the pointer-file hash, then compared selection evidence including extra provenance fields against the metric-only contract output; both helper assertions were corrected using the actual schemas. Original research artifacts, budgets, policies and attempts were untouched; no trial was repeated. Raw prices, numeric performance, curves and detailed local paths remain private. `publication.json` is copied byte-for-byte from the exact supplied supervisor's persisted descriptor, not an agent-authored replacement. Runner completion and independent remote publication verification remain distinct gates.

## Limitations and next experiment

Historical OOS is jointly computed/stored, exposed and reused, not an untouched holdout. Provider-defined adjusted-price returns are not dividend-reinvested total returns. Current-selected equity/ETF membership is non-PIT with survivorship bias; historical delisting/suspension coverage, calendars and corporate actions remain uncertified. Incremental prefixes retain older acquisition vintages and do not certify corrections outside overlap. Volume/session definitions differ across markets. No statistical significance or multiple-testing certification is claimed. Existing #13, #28, #16 and #74 track these limitations; separate supervisor issue #93/PR100 is not repaired inside this research set.

Next experiment was preregistered before trials: baseline `close >= 0.95 * lag(max(high, 252), 1)`, comparing proximity thresholds 0.90 and 0.98 with the same prior-bar window. Reason: the next uncovered executable backlog family contrasts continuous price-strength exposure near a prior high with intermittent volume bursts, rather than retuning this family on exposed OOS. The 252-bar window is a trading-bar proxy, not exact calendar weeks. Proposal #102 records deferred scope from origin #101. No near-high trial was run.

## Validation and integration boundary

Rust `cargo test --locked --offline`: 30 passed, one intentional process-holder helper ignored. Full Python unittest discovery: 246 passed. Synthetic regressions are separate from actual frozen market-data research and Runner.verify. Only current-set research artifacts are committed. Shared backlog, src, tools, Cargo, config, dashboard, older research/results and other profiles are unchanged. Tracking #101 remains open; opening a PR does not close it. No main merge/auto-merge, deployment/release, scheduler change, purchase, live trading or account/order API was performed. Outer day-ledger finalization belongs to the parent supervisor and is not rewritten by this session.
