# Thematic daily-history expansion (#57)

## What this version is / is not

`universes/thematic-v1.json` fixes an initial **96-candidate** cohort (48 US, 48 KR) before collection or strategy scores. The existing24 are retained, with sector/thematic ETF proxies and equities spanning manual present-day research themes. The catalog is a coverage hypothesis, not a claim that every instrument has data since2000, all themes are independent, or every period's historical leaders are present.

Its classification is explicitly as of2026-11-13, `point_in_time=false`. Do not backdate current themes, ETF constituents or survivor membership. Price bars before ETF inception are never synthesized. Historical membership/delistings and reliable exchange calendars remain #13/#28 limitations. The KR equity-heavy and US ETF-heavy cohorts are not matched portfolios; existing equal-symbol engine weights are not theme-balanced allocation. No theme-rotation signal is implemented by this data change.

## Version boundary

The active daily operating checkout remains pinned atbc99433. Nothing here refreshes its receipts, changes schedules, raises its600request acquisition budget, or overwrites old snapshots/results. Default collector/schema2 continues to mean the exact legacy24. Opt-in catalogs use frozen schema3 and the contract in [universe-contract.md](universe-contract.md). Costs, lag, signals, IS/OOS boundary and metrics are unchanged; historical OOS remains exposed. Compare versions only with explicitly identical common inputs/window, not by attributing changed universe/history scores to an engine improvement.

## Bounded engineering bootstrap

This is separate from one daily research set. Its preregistered engineering acquisition budget is at most6000HTTP attempts and120minutes from original initialization, with at most600attempts/20minutes per child, fixed2000-01-01 start and2026-11-13 exclusive cutoff for the initial validation. At batch-size12 the initial catalog has8 batches. Conservative pre-reservation counts failed/interrupted children too. Never raise caps or change dates/catalog/source on resume to start the budget over. No automatic rerun of successful batches; incomplete/failed/live ownership is a stop requiring investigation, not an invitation to delete locks or partial output.

The intended interface is documented below; verify actual CLI help and tests before running. A command example is not evidence of collection:

```sh
python3 tools/collect_universe.py \
  --universe-file universes/thematic-v1.json \
  --env-file "$HERMES_HOME/.env" \
  --token-file "$HERMES_HOME/private/toss-token.json" \
  --output '<NEW private output outside Git>' \
  --start-date 2000-01-01 --cutoff-exclusive 2026-11-13 \
  --max-attempts 6000 --max-minutes 120 --batch-size 12
```

Use the actual configured shared token path; do not infer one from this example or issue a separate token client. Credentials and all raw quotes/CSV/metrics stay in700/600 private storage. A complete root snapshot is only published after all96 configured identities pass preserved price/split/coverage checks; blocked/too-short/unavailable symbols cannot be silently omitted. Per-symbol observed first dates are coverage facts, not independently certified listing dates.

## Parent acceptance before calling expanded data ready

1. Run legacy/full Python and Rust suites, scoped diff/format checks and an independent correctness/security review.
2. Confirm Python catalog acceptance matches native schema3 validation, including rejected duplicate identifiers, aliases, paths, metadata types, unsupported PIT claims and tampering. Confirm schema2 remains exact24.
3. Run actual bounded acquisition once against immutable committed source/catalog, preserving request intents/results, raw hashes, failures, batch manifests and total budget. Synthetic fixtures are not market data.
4. Independently verify every CSV/hash, declared catalog membership, actual first/last dates/row counts and all theme coverage/exclusions. Re-read native frozen input and compare legacy common inputs with distinct engineering output IDs; no existing research success IDs rerun or overwritten.
5. Verify remote PR/head/files/checks. Keep issue57 open until each acceptance criterion is supported or explicitly deferred through linked issues. Do not claim PIT assurance, automatic operation, main merge or operating migration from a snapshot/PR alone.

## Initial investigation already observed

The separate two-symbol pilot returned200pre2000 daily candles each for005930/SPY, with stored raw hashes and older cursors; see #57 evidence. It demonstrates availability at sampled dates, not full coverage or the oldest possible date. Official sector endpoints exist, but documented current sector constituent queries do not provide an as-of date; current classifications cannot certify historical membership.
