# Near-high exit hysteresis — research notes

Tracking: #130. This follows #128 and the entry-confirmation comparison in #129. The three preregistered rules share a one-close entry at 95% of the preceding 252-bar high. The stateless baseline exits below 95%; the two latches exit below 93% and 90%, respectively, against the same rolling reference. The existing next-bar execution and machine policies are unchanged.

All three trials succeeded sequentially without repair or rerun. The IS-only ranking placed the 90% exit first, then 93%, then the baseline. In exposed OOS, the selected rule had higher mean Sharpe than baseline but a deeper mean drawdown and negative excess CAGR versus buy-and-hold in both markets. The unchanged policy returned `defer`, not adoption. The ranking does not establish reduced turnover as the mechanism; buffered exits also alter reentry opportunities.

Plan checkpoint: `beaa9433f1f43be7dd664b03294b46b1fc253955`. Selection checkpoint: `9eb4a17d608901c0a6920a9b1aad593c3fe43647`. Private lessons SHA-256: `2bbc021a5c5d66663c4e317dae8251a4a34acf9ed27299e32b4984491b57b846`. Runner verification passed. Only the exact supervisor-rendered `publication.json` records completion.

Historical OOS overlaps prior work and was jointly computed with IS; it is not independent validation. Provider-adjusted prices are not dividend-reinvested total returns. The present-day universe has survivorship bias, and calendar and corporate-action coverage are not certified (#13, #28).

Next experiment, deferred in #131: hold both thresholds at a stateless 95% and compare 252-, 126- and 63-bar references. This tests whether a shorter reference allows earlier reentry after a decline without excessive whipsaws, rather than retuning exits on exposed OOS.
