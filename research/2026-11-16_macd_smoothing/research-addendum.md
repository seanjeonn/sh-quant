# MACD smoothing — qualitative research addendum

Tracking issue #85; source proposal #69; prior Donchian #68 / PR #70. Set `2026-11-16_macd_smoothing`.

## Hypothesis and bounded preregistration

Hold while `ema(close, 12) - ema(close, 26)` exceeds its own signal EMA. Fast/slow windows remain 12/26; baseline signal smoothing 9, v001 6, v002 12. This represents sustained above-signal positioning, not a single-bar event. Existing next-bar execution, costs, weighting, splits and machine policies were unchanged.

The backlog, prior family conclusions, current issues and open PRs were reviewed read-only. EMA/defer, RSI/reject, Bollinger/defer, momentum/reject and Donchian/defer were already covered; no legacy EMA set was rerun. MACD was the first executable unfinished family and these windows were already specified by #69 before today's results. The approved daily request supplied scope; proposals were not treated as engineering authorization.

Private schema2 plan: three sequential attempts, zero repairs, sixty-minute runner cap subordinate to the unchanged stable supervisor-scope pointer. Only the supervisor's already frozen snapshot was used. No acquisition, credential read, budget reset or scope alteration occurred. An initial preregistration was rejected before registry initialization because next-experiment prose contained comparison notation matching the template-marker guard; its original bytes were preserved privately. The next-experiment wording was clarified before successful initialization, without changing candidates or observing trial scores. Initial shell diagnostics refused by the CLI approval gate were not successful verification or research attempts.

Private plan SHA-256: `54782d558469d0d15cb3f55abc46d68786b3457b273df4e193d74307cf513f83`.
Plan checkpoint: `ab09b1a4eb01d8c8d3298c1274cb24b1e8d96450`.
Selection checkpoint: `563ae1cceb9a359b45e01cb61cda74a5b7673170`.
Pinned engine: `06a6b6c45e8f4ade6e5a99fa785b94b3aa9bb135`.
Frozen manifest SHA-256: `5f714c8b28a2532c027bc9604a904d79d7e3beb8d4073ab1bc7d7907ee97ba24`.

Both exact remote commit/path descriptor blobs and branch state passed runner checkpoints. No trial preceded the plan checkpoint; no evaluation preceded the selection checkpoint. Checkpoint ancestry is preserved without rebase/reset/force-push.

## Actual evidence and conclusion

All three preregistered candidates succeeded sequentially once, with exit code zero, no failed native trial, timeout, repair or successful-ID rerun. Runner.verify recomputed policy results and validated immutable result/index/detail/log hashes, report and candidate lessons. Registered worktree, private plan source/hash, stable supervisor pointer, binary path/hash, manifest path/hash, engine revision and source fingerprints were compared with supplied evidence. Frozen CSV hashes were verified during initialization and subsequent runner verification.

Under `mean_is_sharpe_v1`, IS-only ranking was v002 (12), baseline (9), v001 (6). The selected 12-bar smoothing maximized equal-weight US/KR IS Sharpe under fixed tie-breaks. The faster variant reduced the development objective while the slower variant improved it. Selection lies at the tested grid edge; this finite comparison is not a global optimum, robustness or significance certification. No OOS-based grid extension was made.

Fixed `sharpe_excess_mdd_v1` conclusion: `reject`. All candidates had positive OOS Sharpe but negative excess CAGR versus same-data buy-and-hold in both markets. The selected candidate had lower mean OOS Sharpe than baseline despite less severe mean drawdown; negative excess CAGR in both markets and the Sharpe comparison meet the fixed rejection condition. This is a supported completed negative hypothesis, not an execution blocker or investment adoption.

Private numeric report SHA-256: `c27caf3df81a357adcaea2196a8d130faa9f49127740f06cb523ef4659861756`.
Private evaluation SHA-256: `8b6776fc45e250f80028291aa0529d8e5167a172d12dcabee031db2f0f4ecf84`.
Private candidate lessons SHA-256: `58b0d5d230dc979a3266d2908f84f743b8acd8b27cefff2c69c41a0f6b28c4cd`.

Numeric selection, evaluation, report and all candidate lessons were inspected privately. Quotes, performance values, curves, detailed local paths and logs remain outside Git. `publication.json` is copied byte-for-byte from the deterministic descriptor persisted by the exact supplied supervisor publication command using its supplied config. This qualitative addendum is not a replacement publication descriptor.

## Limitations and next experiment

Historical OOS is exposed, reused and jointly computed/stored, not independent or untouched validation. Toss adjusted-price returns are provider-defined, not dividend-reinvested total return. The expanded current-selected equity/ETF universe is not historical point-in-time membership; survivorship, delisting/suspension coverage and calendar/corporate-action completeness remain uncertified. Incremental prefix vintages and corrections outside overlap are not certified. Earlier smaller-universe studies cross a data-version boundary. No theme balance, exchange-calendar completeness or statistical significance is claimed. Existing #13, #28, #16 and #74 retain those limitations.

Preregistered next hypothesis: a 200-day SMA trend filter plus RSI(2) pullback; enter above the SMA when RSI falls below 10, exit above RSI 50 or below the SMA, compare entry thresholds 5 and 15. Reason: directly executable trend-conditioned mean reversion contrasts MACD acceleration without retuning exposed MACD OOS. The intervening inverse realized-volatility-targeting backlog item first needs an exact executable-semantics review; lack of a dedicated primitive is not proof that a valid composition is impossible. Do not substitute price-level volatility for return volatility. Proposal #88 records the future comparison and this prerequisite gap with origin #85. Neither family was executed today; future scope/duplicates must be checked again.

## Validation and integration boundary

`cargo test --locked --offline`: 30 passed, one intentional process-holder helper ignored. Python unittest discovery: 246 passed. The first combined validation command timed out at the tool boundary; its log was preserved, then validation resumed without research reruns and passed. These regression tests are separate from actual market trials and Runner.verify. Private logs remain private. Whitespace checks passed before checkpoint commits.

Only current-set research files are published. No shared backlog, source/tools/Cargo/config/dashboard, pre-existing research/results, scheduler or another profile was modified. Research PR targets main; main merge/auto-merge, deployment/release, paid services and live/account/order APIs are outside scope. Issue #85 remains open pending normal integration; an open PR is not a merge or deployment.
