# Prior-252-bar high proximity — qualitative research notes

Tracking #116; source #102; predecessor #101 / PR #103.

The backlog baseline holds when the close is at least 95% of the prior 252-bar high. The two alternatives change only the threshold, to 90% and 98%. The high excludes the signal bar; 252 bars approximate, but are not exactly, 52 calendar weeks. The unchanged engine applies the signal on the next bar. Unlike the earlier Donchian experiment, this rule does not latch a breakout position until a separate exit condition. This set tests whether looser or stricter participation improves the declared development objective, not whether past performance predicts future results.

## Evidence and decision

Three preregistered candidates ran successfully in sequence, with no repairs or reruns. `mean_is_sharpe_v1` selected the 90% rule, followed by the 95% baseline and the 98% variant. This ranking covers only those three thresholds. After the selection checkpoint, `sharpe_excess_mdd_v1` returned `defer`: the selected variant had positive OOS Sharpe in both markets and higher mean OOS Sharpe than baseline, but it lagged the corresponding buy-and-hold benchmarks in both markets and had worse mean drawdown than baseline. It qualified for neither acceptance nor rejection under the fixed policy. No strategy is adopted.

Plan checkpoint `e23fad95ff735a3c5ecbfa39151dc3a435a5bbf9` preceded all trials; selection checkpoint `f05c3405d57fea0b3d2023084f7ccdeec3a67a32` preceded evaluation. Both were checked against their exact remote blobs. Runner verification recomputed the declared policies and checked immutable evidence and final artifacts. The supervisor-generated `publication.json` is the sole completion record and contains the private report and evaluation SHA-256 digests. Private lessons SHA-256: `2c892e3603b36db9240cf607770a34ce9789b6577419c1b5c2bbcfae72c3d01e`.

## Limits and follow-up

Historical OOS was reused and computed alongside IS; it is exposed, not independent validation. Provider-adjusted price returns are not dividend-reinvested total returns. The current-selected universe is not point-in-time, and calendar and corporate-action coverage are not certified. Related limitations: #13, #28, #16 and #74. Only the frozen snapshot was used; no new data was acquired and no credentials were read.

Preregistered follow-up #117: hold the 95% proximity threshold fixed and compare the unfiltered rule against requiring a rising 200-bar simple moving average over 20 or 60 bars. This isolates whether trend direction can screen out rebounds in falling long-term trends without further tuning proximity on exposed OOS. No slope-filter trials were run in this set.
