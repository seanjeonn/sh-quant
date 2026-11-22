# Near-high confirmation — research notes

Tracking: #127. Follow-up to #125 and #124. The comparison kept the 95% threshold and prior 252-bar high fixed and varied the number of consecutive qualifying closes (one, two, or five). Each close was compared with its own prior high, excluding its signal bar. A nonqualifying close ends exposure under the same next-bar execution rule for every candidate.

All three preregistered trials succeeded sequentially, without repairs or reruns. IS ranked one-bar confirmation first, two-bar second, and five-bar third. Neither longer confirmation improved the preregistered IS objective in this comparison. The selected baseline had negative OOS excess CAGR versus buy-and-hold in both markets, and its mean OOS Sharpe was equal to the baseline by definition. The fixed policy rejected it; no candidate was adopted.

Plan checkpoint: `e512a28cd8cf4b412f74b39bc26689ac28b99e4a`. Selection checkpoint: `73dc7f2b2012ef6d67353e257251fab33f65d531`. Private lessons SHA-256: `f8d8fc10709b6bd2ddf06dd8bda67959e7b5706e555dc01500ae32cf94dcd90e`. Only the exact supervisor-rendered `publication.json` records completion.

Historical OOS overlaps earlier studies and was computed alongside IS; it is exposed, not independent validation. Provider-adjusted prices are not dividend-reinvested total returns. The current universe is subject to survivorship bias, and calendar and corporate-action coverage are not certified (#13, #28).

Next experiment, deferred in #128: keep entry at 95% with one qualifying close and compare same-threshold exit against exits below 93% and 90%. This tests whether an exit buffer reduces threshold churn enough to offset slower exits in declines, without changing entry timing.
