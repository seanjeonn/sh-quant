# Historical-data evidence and unknowns — #61 / #13 / #28

Evidence reviewed2026-11-14. This records documentation support and a small issuer sample, **not live endpoint validation or certification of all96 instruments**. Price-history availability, listing facts, calendar completeness, suspensions, corporate actions/total return and point-in-time membership are distinct verdicts.

## Corrected capability boundary (official Toss OpenAPI1.2.28)

Parent independently fetched [canonical OpenAPI JSON](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json) and inspected query parameters and StockInfo schema.

- `/api/v1/stocks`: `symbols` query, up to200. StockInfo includes nullable `listDate` (description says information unavailable ->null), nullable `delistDate`, current statusSCHEDULED/ACTIVE/DELISTED. These fields **exist**; lack of independent verification must not be described as absence of the API. No metadata as-of/date query is documented here.
- `/api/v1/stocks/all`: market/status filters includeDELISTED, but a filter alone does not certify comprehensive historical delisted coverage or point-in-time membership.
- `/api/v1/market-calendar/KR` and `/US` **do accept a `date` query**. [MarketInfoApi](https://openapi.tossinvest.com/openapi-docs/latest/api-reference/Apis/MarketInfoApi.md) describes previous/current/next three business-day information; US input is US local date and response times areKST. Historical retention/minimum date and full2000–present coverage are not guaranteed by the parameter's existence.
- [SectorApi](https://openapi.tossinvest.com/openapi-docs/latest/api-reference/Apis/SectorApi.md): current proprietary multi-membership classification; constituent stock/ETF queries use sectorId+marketCountry, not an as-of date. Delisted ETFs are excluded. Performance duration is not a historical membership date.
- Candle `before` is an inclusive time upper bound, not the time when adjusted historical data/classification became known. No independent complete corporate-action ledger has been verified by this review.

The daily price collector remains OAuth/candles only. A separately tested, bounded read-only metadata inspection interface may query only stocks and date calendars under explicit feature61 authorization. It must preserve raw responses privately, share the existing token/issuance mutex and its own small declared total budget, and never broaden into account/orders or silently return today's calendar for a failed historical query.

## Small issuer sample, not a96-row certification

- **SPY:** State Street's [official product page](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy) lists `Inception Date: Jan22 1993`. This is an issuer-presented inception fact, not reconstruction of exchange transfers, all past constituents or the earliest actually executed trade.
- **KR069500:** Samsung Asset Management's [official factsheet dated2026-07-31](https://www.samsungfund.com/sheet/20260805/2ETF01_20260731.pdf) states `상장일2002.10.14`. Do not substitute it for a different fund establishment date; distributions/top holdings in that factsheet are partial-period facts, not a complete historical action/constituent ledger.

## Remaining explicit unknowns / finite evidence plan

1. Maintain per-identifier listing/inception facts with exact source URL, source date, retrieval date, observed first candle separately and an evidence status. Unavailable/null is unknown, not a fabricated date. Metadata supplied today is not proof it was known historically.
2. Probe a bounded declared sample of historical calendar dates and inspect returned date fields, not just HTTP200. Store unavailable/unsupported/mismatch outcomes; never certify the full historical calendar from a few successful samples.
3. Build historical calendars from authoritative annual schedules and exceptional-closure notices where accessible. Without calendar/suspension evidence, gaps cannot automatically be called holidays and expected-bar completeness remains unverified.
4. Historical suspension/delisting/corporate-action events require exchange/issuer records; avoid inferring delisting from the final candle or treating market transfers as economic extinction. Current-selected survivors remain biased even after adding instruments.
5. Broader historical catalogs/paid services may require credentials, licensing or subscriptions. Do not purchase/register/contact outside organizations without the applicable approval; expose source blockers rather than fabricating a clean universe.

## Useful official source entry points (further full-coverage work pending)

- [Nasdaq current Symbol Lookup](https://www.nasdaqtrader.com/trader.aspx?id=symbollookup)
- [Nasdaq trade-halt resources](https://www.nasdaqtrader.com/Trader.aspx?id=TradeHaltRSS)
- [NYSE hours/calendars](https://www.nyse.com/trade/hours-calendars)
- [KIND delisting records](https://kind.krx.co.kr/investwarn/delcompany.do?method=searchDelCompanyMain)
- [KIND detailed disclosures](https://kind.krx.co.kr/disclosure/details.do?method=searchDetailsMain)
- [KRX calendar entry](https://global.krx.co.kr/contents/GLB/05/0501/0501060000/GLB0501060000T3.jsp)

These entry links are not a claim that every year/page/event was collected. Do not close #13/#28 or the historical-certification checkbox in #57 from this document or from successful raw-price collection. Actual inspection results, if executed, require a separate immutable request/response/provenance record.
