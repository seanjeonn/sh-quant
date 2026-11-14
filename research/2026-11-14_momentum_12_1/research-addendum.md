# 12-1 momentum — qualitative research addendum

Tracking issue #65. Set `2026-11-14_momentum_12_1`. Source proposal #54; prior family #53.

## Hypothesis and bounded preregistration

The first executable unfinished backlog item was positive twelve-month momentum excluding the latest month. Prior EMA/defer, RSI14/reject and Bollinger/defer lessons were reviewed read-only. The preceding set and #54 had already specified horizons 252, 231 and 273 with a 21-bar exclusion before today's scores. No legacy EMA set was rerun.

Baseline: `lag(close, 21) > lag(close, 252)`.
Variant v001: `lag(close, 21) > lag(close, 231)`.
Variant v002: `lag(close, 21) > lag(close, 273)`.

These are distinct executable signals; trading bars approximate months. The private schema2 plan allowed three sequential attempts, sixty minutes and zero repairs, subordinate to the unchanged supervisor lease. No engine, costs, splits, weighting, execution or machine policy changes were made. Only the supervisor's already frozen snapshot was used; this research session acquired no data and read no credentials.

Private plan SHA-256: `6fade3f38ea91928728fbfbdb48d996539a311c404c42bd8244381ae71ca80ba`.
Plan checkpoint commit: `1c20a7881d6f8a3fae031349ae5eaf2a30ce19a6`.
Selection checkpoint commit: `b5bb3d0aa47921a13f8f6223fd08263acdfb6771`.
Pinned engine: `a9822aa78622c1c6a700e287288de8c5aba800da`.
Frozen manifest SHA-256: `08c6b98524956e242d5cc49445e185949151f8880d60eb3d3579dea9e234d507`.

Both checkpoints verified exact remote commit/path blobs and branch state before their next phase. No trial preceded the plan checkpoint; no evaluation preceded the selection checkpoint.

## Actual evidence, selection and conclusion

Baseline and both variants succeeded exactly once, sequentially, with exit code zero. There were no failed strategy trials, repairs, timeouts or successful-ID reruns. Immutable start/child/end records, input fingerprints and actual result/index/detail/log hashes were validated by Runner.verify. Registered worktree, plan source, supervisor pointer, binary, manifest and engine were independently matched to the supplied supervisor context rather than just accepting registry declarations.

The preregistered `mean_is_sharpe_v1` ranking was v001 (231), baseline (252), v002 (273). US/KR equal-weight IS Sharpe means determined selection, with the unchanged fixed tie-breaks; OOS did not determine ranking. The shorter horizon improved the development objective, while the longer horizon worsened it. This finite comparison does not establish a global optimum or statistical robustness.

Final machine conclusion: `reject`, under `sharpe_excess_mdd_v1`. The selected v001 had positive OOS Sharpe but negative excess CAGR relative to same-data buy-and-hold in both markets. Its mean OOS Sharpe did not improve over baseline, satisfying the fixed rejection condition. Mean OOS drawdown was not worse than baseline, but this alone does not satisfy adoption. All three candidates had positive OOS Sharpe and negative OOS excess CAGR in both markets. This is a supported negative research conclusion, not a data/execution blocker or trading recommendation.

Private numeric report SHA-256: `1ddc596a96044cc681222a44018e359de24e0008ab26bf084bd962d3be6d7dc0`.
Private evaluation SHA-256: `9980280cafeb6477b7293146a50da3b2a90b9fe01f43a3cca834eba29e6325c5`.
Private candidate lessons SHA-256: `a5bbe3b6ad928d77007c46dcd2a881f593aee4d2213ccb0f1b0b5bf49f8345a1`.

Actual per-candidate numeric report and lessons were inspected privately. Raw quotes, numeric performance, curves, detailed local paths and logs remain outside Git. `publication.json` is copied byte-for-byte from the exact supplied supervisor publication command's deterministic output file. This qualitative addendum is separate, not a replacement descriptor. Runner completion and independently verified remote publication are separate gates.

## Limitations and next experiment

OOS is jointly computed/stored and historically exposed, not an untouched holdout or independent validation. Toss provider-defined adjusted-price returns are not dividend-reinvested total returns. The expanded current-selected equity/ETF universe introduces a new engine/data comparison boundary versus prior smaller-universe studies; it is not historical point-in-time membership. Survivorship, delisting/suspension coverage, uncertain internal historical dates, calendar/corporate-action completeness and older carried-prefix correction coverage remain limitations. Current provider listing dates must not justify truncating observed earlier bars. Existing follow-ups #28, #13 and #16 remain unresolved. No significance, balanced-theme or complete exchange-calendar certification is claimed.

The next experiment was preregistered before today's trials: Donchian entry above the prior 55-bar high with exit below the prior 20-bar low, comparing entry windows 40 and 70 with the same exit. Baseline `latch(close > lag(max(high, 55), 1), close < lag(min(low, 20), 1))`. Reason: next executable backlog family and a price-extreme trend contrast, not more lag-horizon tuning on observed OOS. Deferred proposal #66 links origin #65. No Donchian trial was executed today.

## Validation and integration boundary

`cargo test --locked --offline`: thirty passed, one intentional process-holder helper ignored. Python unittest discovery: 237 passed. An initial 120-second test command timed out; the full rerun completed with its private log retained. Synthetic negative-test diagnostics are not actual market-data failures or results. These regression tests are separate from three actual frozen market-data trials and completed/reject Runner.verify.

Research branch `research/2026-11-14_daily` is based on pinned core working branch `feat/61-expanded-daily-refresh`, not main. Only current-set research files and its completed backlog checkmark are publication scope. No main merge, auto-merge, deployment/release, account/order API, live trading, scheduler/config edit or unrelated work was performed. Issue #65 remains open pending normal integration; PR creation is not issue closure.
