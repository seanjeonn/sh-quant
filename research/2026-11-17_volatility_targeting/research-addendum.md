# Capped realized-return volatility sizing — qualitative addendum

Tracking #90. Set `2026-11-17_volatility_targeting`. Source executable-review request #88; prior MACD #85 / PR #89.

## Hypothesis and bounded preregistration

Inverse realized daily-return volatility sizing may improve risk-adjusted outcomes. Annual target 0.15 is fixed. Baseline uses a 20-bar sample standard deviation of fractional daily simple returns; v001 uses 10 bars, v002 uses 40 bars. All use `clip(0.15 / (15.87450786638754354 * std(pct(close, 1), n)), 0, 1)`. The annualizer was computed as sqrt(252) before registration. These are distinct executable signals, not metadata-only variants.

Reviewed prior EMA/defer, RSI14/reject, Bollinger/defer, momentum/reject, Donchian/defer and MACD/reject lessons, backlog, current issues and the open MACD PR. MACD is already covered by #85 / PR #89 despite its unchecked backlog entry and was skipped. Volatility targeting is the first remaining backlog item. Inspection of `src/expr.rs` established that `pct` returns fractional simple returns, `std` accepts a nested series, and arithmetic/clip provide capped inverse annualized sample return volatility. This resolves the earlier executability concern in #88 without inventing primitives, changing the engine or substituting price-level standard deviation. No legacy EMA set was rerun.

The private schema2 plan allows exactly three attempts, zero repairs and sixty minutes, subordinate to the unchanged absolute stable supervisor-scope pointer. Only the supplied frozen snapshot and pinned binary were used. No acquisition or credential reads occurred in this research session. Native trial warmup NaN becomes flat; zero estimated volatility saturates capped exposure under existing semantics. Per-instrument sizing is not a guaranteed 15% portfolio volatility target, and leverage is not allowed.

Private plan SHA-256: `8cfcbb2cae06afb69cf5f1688a8c134dbd78576935dbdeb2a23bcdbe1be14540`.
Plan checkpoint: `c7530111df4b5c3564852c4fa9aa68add1d5012d`.
Selection checkpoint: `10ce7dc2e7794fdd87a1ec57205240018ecaba79`.
Engine revision: `06a6b6c45e8f4ade6e5a99fa785b94b3aa9bb135`.
Frozen manifest SHA-256: `add734fe4592ce0bfe94910a745d96da1d2278a347682729a777232e32f6d6cd`.

Each checkpoint read the exact remote commit/path blob and branch state before its next phase. No trial preceded the plan gate; no evaluation preceded the selection gate. Checkpoint ancestry is preserved, with no rebase/reset/force push.

## Actual evidence and conclusion

All three preregistered candidates succeeded once, sequentially, exit code zero, without failed strategy trial, timeout, repair or successful-ID rerun. Runner.verify checked immutable start/child/end evidence, results/index/detail/log hashes and recomputed selection, evaluation, report and candidate lessons. Registered worktree, private plan source, stable scope pointer, binary path/hash, manifest path/hash and engine revision were independently matched to the supplied supervisor evidence. Code-tree pins match the supplied frozen revision; the public catalog hash also matches.

IS-only ranking was v002 (40), baseline (20), v001 (10). Selection used `mean_is_sharpe_v1`: equal-weight US/KR IS Sharpe means and unchanged fixed tie-breaks. The longer window improved the development objective; the shorter window worsened it. This three-window comparison does not establish a global optimum or statistical robustness. OOS did not alter candidates or selection.

Fixed `sharpe_excess_mdd_v1` conclusion: `defer`. All candidates had positive OOS Sharpe but negative excess CAGR against same-data buy-and-hold in both markets. Selected v002 improved mean OOS Sharpe over baseline and slightly reduced mean drawdown severity, but negative mean excess CAGR prevents acceptance. The improved mean Sharpe prevents the fixed rejection condition. Its US drawdown was worse than baseline even though the cross-market mean improved. This is a supported completed research conclusion, not adoption, operational blockage or trading advice.

Private numeric report SHA-256: `33019658732450b9f07b902a96fdba20d4a6887538a804b4b245f5518e68d71b`.
Private evaluation SHA-256: `185565c9909ec459ddb7a8679cdf20f184c1080117e4f0b199893bd8fab04fd0`.
Private candidate lessons SHA-256: `0998fe410f902f2f3127f8d9a50379f684f3d24cbd6d6409064e56bc8a12be30`.

Actual per-candidate numeric evidence and lessons were inspected privately. All numeric performance, quotes, curves, raw logs and detailed local paths remain outside Git. `publication.json` is copied byte-for-byte from the file persisted by the exact supplied supervisor publication command with the supplied config path. This addendum is separate interpretation, not a replacement descriptor. Runner completion and remote publication verification are separate gates.

## Limitations and next experiment

Historical OOS is exposed, jointly computed/stored, repeatedly reused and not independent or untouched holdout. Provider-defined adjusted-price returns are not dividend-reinvested total returns. Current-selected expanded equity/ETF membership is non-PIT with survivorship bias, incomplete historical listing/delisting/suspension knowledge and uncertified exchange-calendar/corporate-action completeness. Incremental snapshots carry older prefix vintages and cannot certify corrections beyond overlap. No theme-balance, multiple-testing adjustment or significance claim is made. Existing #13, #28, #16 and #74 remain applicable.

The next experiment was preregistered before trials: enter a short-term RSI(2) pullback below 10 only above the 200-bar SMA; exit when RSI(2) exceeds 50 or close falls below the trend filter. Compare entry thresholds 5 and 15 with identical trend window and exits. Reason: next executable backlog family and conditional reversion contrast, not further tuning on exposed OOS. Existing proposal #88 now links originating #90 as well as #85; no duplicate proposal and no RSI trial today.

## Validation and integration boundaries

`cargo test --locked --offline`: 30 passed, one intentional process-holder helper ignored. Full Python discovery ran 246 tests and reported two failures, both in research-ledger metadata contracts: the hardcoded family map returns unknown for this new family, and a blanket forbidden-word test matches the safe set ID token `volatility`. Reproducible bug #91 records these failures and separate engineering scope. No tool, test, policy or set ID was changed to hide them. These reporting/test-extensibility failures do not invalidate successful native trials or completed/defer Runner.verify; CI is not claimed green. Diff whitespace checks passed.

The initial plan init was rejected before registration because the next-experiment prose embedded comparison operators that matched the placeholder guard. The rejected private plan is preserved; wording was changed to equivalent prose before successful registration, with no trial or budget reset. Local arbitrary-Python inspection probes were denied by unattended tool policy and were not executed; normal CLI/file tools were used instead. No approval policy was changed.

Only this set's research artifacts are committed on `research/2026-11-17_daily`, with PR base `main`. Shared backlog is unchanged; completion is recorded only by this set's `publication.json`. Tracking #90 remains open pending normal integration. No main merge/auto-merge, deployment/release, scheduler/config changes, paid service, live trading or account/order APIs were performed.
