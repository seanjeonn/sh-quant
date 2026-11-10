# Toss private daily data — #26

## Purpose and boundaries

This engineering path prepares daily candles without backtesting, verifies a frozen snapshot, and keeps restricted data outside every Git checkout. It is not a scheduler, sweep runner, live trader, or a guarantee that every symbol has complete exchange-calendar coverage. The linked research remains blocked until actual provenance and quality checks pass.

## Interfaces

The approved minimal implementation separates Python acquisition from Rust execution rather than maintaining two OAuth clients:

```text
python3 tools/prepare_toss.py --env-file <private-env> --token-file <shared-private-token-json> --output <new-private-snapshot-dir> --start-date 2015-01-01 --cutoff-exclusive <YYYY-MM-DD> --max-attempts 600 --max-minutes 30 --min-interval 0.25
cargo run --release --locked -- run strategies/<new-id>.toml --data-manifest <private-snapshot-dir>/manifest.json --output-dir <private-results-dir>
```

These interfaces are implemented/validated under #26; a documentation example alone is not execution evidence. The default Yahoo `run` path is retained for compatibility. Do not put Toss input into a `.yahoo.csv` file or fall back from frozen data to a network source. Before using `lesson` or `fail`, choose the matching private `--output-dir`; never modify pre-existing IDs/results from another set. Frozen data/output reject repository destinations and unsafe symlinks; raw responses/results/token files must be 600 and their private directories 700.

## Data contract

`manifest.json` schema version 2 includes `provider: toss`, `adjusted: true`, `timezone: Asia/Seoul`, exclusive completion cutoff, preparation timestamp, `status: complete`, and exactly the current 24-symbol fixed universe. Each entry records market/ticker/currency/session, relative CSV path, SHA-256, row count and first/last trading dates. CSV header is `date,open,high,low,close,volume` with ascending unique dates.

The frozen loader verifies the manifest and all CSV files before and after execution. Invalid OHLC, missing/extra symbols, hash drift, path escape, currency/session mismatch or incomplete status fails closed. It does not repair prices, impute missing trading days, skip a failed symbol or refresh data. A raw-provider quality error is data_setup blocked, not a research rejection.

## Read-only acquisition and tokens

Use only `/oauth2/token` and `GET /api/v1/candles`; account and order APIs are out of scope. A client has one valid token. Reuse the shared private token under an interprocess lock; coordinate with any existing collector before issuance. Never run independent token refreshers for kingfish and this preparation tool.

Candles use `interval=1d`, explicit `adjusted=true`, `count=200`, and the exact `nextBefore` cursor returned by the server. Encode `+` in timezone offsets with URL encoding. Retain a distinct raw response and start/end attempt record for every candle request/retry, not only successful pages. Never persist OAuth response bodies in raw logs. Bound all retries and authentication requests within 600 total attempts and 30 minutes; respect Retry-After and stop on 403/credential errors. The configured interval is a minimum, not evidence of any server quota.

Inspect finite positive OHLC, high/low bounds, nonnegative volume, ordering/duplicates, currency, timestamps, coverage and completion cutoff. Zero-volume candles can be legitimate. Late listing and unavailable history must be disclosed, not fabricated. Calendar completeness and historical trading suspension are not proven merely by receiving a continuous page chain.

## Return semantics and historical comparability

KR uses integrated KRX/NXT sessions; US daily OHLC is regular-session official pricing while volume may include extended hours. Timestamp trading date is not the naive UTC date; preserve the local-market date with DST handling. Exclude the still-in-progress trading day.

Toss `adjusted` is not Yahoo dividend-adjusted total return. US small dividend/distribution events can be absent from the adjustment. Unless separate cash distributions are verified, describe results as provider-defined adjusted-price returns, not dividend-reinvested total returns. This provider switch establishes a new data-version boundary, not an apples-to-apples correction of Yahoo performance. The engine's costs, splits, weighting, signal lag and metric calculations remain unchanged. IS/OOS are still jointly computed: holdout status is **exposed**, not untouched or sealed.

## Publication / redistribution

The official FAQ forbids redistribution of supplied information to third parties even for noncommercial use. Raw responses, OHLCV CSV, tokens, private manifests with sensitive local paths, logs containing metrics, and equity curves must remain private outside Git. Do not publish Toss artifacts through `results/`, `public/`, Discord attachments or Vercel. Until aggregate-result use is confirmed, keep numeric strategy/benchmark comparisons private too. Confirm the research is for the credential owner's personal investment use; possessing API credentials is not discretionary trading authority.

Public code can include clearly marked synthetic test fixtures; they are never research results. Public research records may contain non-price plan parameters, provenance hashes, run IDs, states, selected candidate identity, limitations and a qualitative conclusion. Keep actual numerical selection/evaluation evidence in private artifacts and link with SHA-256; do not fabricate a public comparison table. Preregistration and candidate selection still require immutable commits/pushes of the allowed descriptor/hash before their next phase. A private report must actually exist and be inspected before any completed claim.

## Actual validation record (2026-11-10 KST)

The first collector invocation refused a 755 private parent before HTTP; its permissions were tightened to 700. The next invocation retained 179 attempts and stopped at the original research symbol `BRK-B` with 404; it did not omit that symbol. A separate read-only `GET /api/v1/stocks` metadata diagnostic returned Toss symbol `BRK.B`. An explicit mapping preserves research identity `BRK-B` while recording source_symbol `BRK.B`; this is not general ticker normalization. The regression test was observed RED then GREEN before the collector reran.

A new immutable snapshot completed all 24 symbols in 372 requests. Including the blocked 179 requests and one metadata diagnostic, 552 total API requests remained within the 600-request acquisition cap. All 24 normalized CSV hashes and per-request raw hashes were verified. The prior 19 flagged dates were present and satisfied Toss OHLC bounds. This does not prove which Yahoo field was wrong or complete exchange-calendar coverage. Failed and successful snapshots remain distinct and private. No strategy was run during preparation. Offline tests, code review and actual preparation are separate evidence categories; this record is not a completed EMA experiment.

Spec review identified two issues: US volume finality was prematurely assumed at regular-close+15min, and 503 Retry-After was ignored. Both were reproduced with failing regression tests and fixed: conservative US20:15 New York / KR20:15 Seoul cutoff (not a provider finality guarantee), and Retry-After honored for all retryable HTTP responses. All retained source rows were subsequently revalidated against their individual response timestamps under the corrected policy: 358 successful raw pages, 24 symbols, 70,210 distinct rows. A new immutable revalidated manifest points to the original manifest hash; original files were not rewritten. The acquisition itself used an uncommitted pre-review collector whose exact source was not independently archived, explicitly disclosed in the private provenance. Revalidation pins the corrected collector SHA-256. No extra market requests or backtests were used for revalidation.

## Verification and follow-up

Run `cargo test --locked`, `python3 -m unittest discover -s tests -p 'test_*.py'`, and `git diff --check`. Offline synthetic fixtures demonstrate implementation behavior, not real-market quality. Actual collection must separately verify 24-symbol coverage, every previously flagged source date, original raw hashes, failure history, completion and current engine revision. Record later listings, calendar limitations and provider differences.

Related: #23 research, #24 source quality, #2 daily collection, #16 IS-only search, #20 broader orchestration, #21 scheduling. PR #8 is a separate conflicting kingfish implementation and is not automatically merged or edited. Main merges, deployments, releases, purchases and live orders require separate approval.

Official sources:
- https://openapi.tossinvest.com/openapi-docs/latest/api-reference/Apis/MarketDataApi.md
- https://openapi.tossinvest.com/openapi-docs/faq.md
