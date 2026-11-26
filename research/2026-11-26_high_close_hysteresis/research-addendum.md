# Highest-close exit hysteresis — qualitative lessons

Tracking: #139. Source: #137, following #136 / #138 and the intraday-high hysteresis comparison in #130 / #132.

All three preregistered candidates completed once on the same frozen snapshot. With entry fixed at 95% of the prior 126-bar highest close, `mean_is_sharpe_v1` ranked the 92% latch exit first, the 94% latch exit second, and the stateless baseline third. This supports the IS ranking hypothesis for these candidates; it does not establish that reduced whipsaw caused the improvement.

Under `sharpe_excess_mdd_v1`, the conclusion was **defer**, not adoption: the selected rule had positive OOS Sharpe but trailed same-snapshot buy-and-hold on OOS CAGR in both markets. Historical OOS is exposed and overlapping prior research, not independent validation. Toss adjusted-price returns do not represent dividend-reinvested total returns; the current-selected universe and unverified historical calendar/corporate-action completeness also limit inference.

Plan checkpoint: `381fab26fead2ab2824cbb748846237bb3881b60`. IS selection checkpoint: `5b36997bac6c3ac81b6978ff209f7ef90e04db82`. Private lessons SHA-256: `a88dde69c49bc36940fda77b9ba954aea21a6dd36e7d8840eb29994513dbb146`. The supervisor-rendered `publication.json` is the sole completion record; private numeric report and evaluation hashes are recorded there.

Next experiment (#140): at the same 126-bar reference and 95% threshold, compare exit after one, two, or three consecutive below-boundary closes. This isolates time confirmation from widening the exit band. No additional trials were run.
