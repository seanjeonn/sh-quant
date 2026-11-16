# Donchian breakout — qualitative research addendum

Tracking issue #68. Set `2026-11-15_donchian_breakout`. Source proposal #66; prior momentum #65 / PR #67.

## Hypothesis and preregistration

Entry above the prior 55-bar high and exit below the prior 20-bar low may capture persistent trends. Baseline `latch(close > lag(max(high, 55), 1), close < lag(min(low, 20), 1))`; v001 changes only the entry window to 40, v002 to 70. Prior-bar thresholds exclude today's extrema; the existing engine applies next-bar execution. No costs, splits, weighting, engine or policy changed.

Prior EMA/defer, RSI/reject, Bollinger/defer and momentum/reject records were reviewed read-only along with backlog, current issues and open PRs. The pinned-core backlog still showed momentum unfinished, but #65 / PR #67 established its completion. It was not rerun. Donchian was the next executable family, with these exact windows already proposed in #66 before today's scores. Today's explicit user authorization supplies research scope, not engineering or acquisition approval.

Private schema2 plan: three sequential attempts, sixty-minute runner cap, zero repairs, subordinate to the unchanged stable supervisor-scope pointer. Only the supplied already frozen snapshot was used. No market-data acquisition or credential reads were performed in this research session.

Private plan SHA-256: `0bcb535921a67ebba08d2d17e5a849a354ead4c7d300ef4175a9784d27d64d62`.
Plan checkpoint: `b28863681ae3e761d00fd65a9a6d2842ab72506b`.
Selection checkpoint: `3def1ecc3972ca328c3539d4170ab477dbca4776`.
Pinned engine: `a9822aa78622c1c6a700e287288de8c5aba800da`.
Frozen manifest SHA-256: `445b6440ac7ed71fd071c4ad2a37e4ce0650b45725c3d4ccedd68d9bfa3d02f9`.

Exact remote commit/path blobs and branch state were checked by each checkpoint. No trial preceded the plan gate; no evaluation preceded the selection gate.

## Actual evidence and conclusion

All three preregistered candidates succeeded once, sequentially, exit code zero, no timeout, failed trial, repair or successful-ID rerun. Runner.verify validated immutable attempt/result/index/detail/log hashes and recomputed selection/evaluation/report/lessons. Registered worktree, plan source, supervisor pointer, binary path/hash, manifest path/hash and engine revision were independently compared with supplied supervisor evidence.

Under `mean_is_sharpe_v1`, IS-only ranking was v002 (70), v001 (40), baseline (55). The selected 70-bar entry window maximized equal-weight US/KR IS Sharpe with fixed tie-breaks. Both variants improved the declared development objective over baseline, but this finite nonmonotonic window comparison is not a global optimum or robustness certification. OOS was not used to change candidates, ranking or policy.

Fixed `sharpe_excess_mdd_v1` conclusion: `defer`. Every candidate had positive OOS Sharpe and negative OOS excess CAGR relative to same-data buy-and-hold in both markets. The selected candidate improved mean OOS Sharpe and had less severe mean OOS drawdown than baseline. Negative mean excess CAGR prevents acceptance; its improvement over baseline prevents the policy's rejection condition. This is a supported completed research conclusion, not execution blockage, adoption or trading advice.

Private numeric report SHA-256: `b4e99fb98141167dcda4b3e47f5e56fbcf6479d8be8b7e0a4885e9ab19bd4d0b`.
Private evaluation SHA-256: `8058e72ac7f445f5eb430d02c0ea0cf689c064a86defb2cdb3b346d7ca26cbf8`.
Private candidate lessons SHA-256: `0baebd030d387bea4dc6e08527cc1e5b7de0157eeb09b1b8495112e795cfb573`.

Actual candidate metrics, ranking, evaluation and lessons were inspected privately; only qualitative comparisons are published. Raw quotes, numeric performance, curves, detailed local paths and logs remain outside Git. `publication.json` is copied byte-for-byte from the deterministic file produced by the exact supplied supervisor publication command. This addendum is separate interpretation, never a replacement publication descriptor. Runner completion and independent remote publication verification are distinct gates.

## Limitations and next experiment

Historical OOS influenced family selection and is jointly computed/stored for each candidate. It is exposed, reused historical data, not an untouched or independent holdout. Toss adjusted-price returns are provider-defined, not dividend-reinvested total returns. The expanded current-selected equity/ETF universe is not historical point-in-time membership; survivorship, delisting/suspension coverage and uncertain internal historical dates remain. Calendar/corporate-action completeness is not certified. Incremental snapshots carry older prefix vintages and do not certify corrections outside overlap. Weekend reuse of latest completed sessions invents no new bars. Comparison to earlier smaller-universe families crosses a data-version boundary. No statistical significance or theme-balance certification is claimed. Existing #28, #13 and #16 remain unresolved.

The preregistered next hypothesis is MACD trend persistence: `ema(close, 12) - ema(close, 26) > ema(ema(close, 12) - ema(close, 26), 9)`, comparing signal smoothing windows 6 and 12 with fast/slow windows fixed. Reason: next executable backlog family and a trend-acceleration contrast, rather than further Donchian tuning on exposed OOS. Proposal #69 records this deferred work with origin #68. No MACD trial was executed.

## Validation and integration boundary

`cargo test --locked --offline`: 30 passed, one intentional process-holder helper ignored. Python unittest discovery: 237 passed. Private test logs retained. These synthetic regression tests are separate from actual frozen market-data research and completed/defer Runner.verify. Diff whitespace checks passed before commits.

Research branch `research/2026-11-15_daily` is stacked on pinned core branch `feat/61-expanded-daily-refresh`, not main. Publication scope is current-set research artifacts and its completed backlog checkmark only. The stale previous-day momentum checkbox is not edited here; its existing PR #67 owns that update. No source/tools/Cargo/config/dashboard/old artifacts, scheduler, main merge, auto-merge, deployment/release, paid service or live/account/order API changes were made. Issue #68 stays open pending normal integration; PR creation alone is not issue closure.
