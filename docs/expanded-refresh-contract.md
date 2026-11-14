# Expanded daily refresh contract — #61 (source #60)

Engineering branch only; preserve existing operating source/receipts/artifacts until a new complete canary-approved version boundary. User explicitly approved all remaining work including main integration and operating transition, not paid sources/orders/live trading or arbitrary caps. Today14:30 daily must remain protected.

## Refresh CLI / immutable snapshot

New `tools/refresh_toss.py` accepts required absolute `--universe-file`, `--universe-sha256`, `--base-manifest`, `--base-sha256`, `--env-file`, `--token-file`, NEW private `--output`, `--start-date`, `--cutoff-exclusive`; options `--max-attempts`<=600 (default600), `--max-minutes`<=20 (default20), `--min-interval`>=0.25. Reuse existing prepare_toss Client/Auth/normalization/token collection mutex and its request/raw logging: no new auth client, account/order or metadata endpoints. Entire workflow shares ONE Client budget/epoch including fallback requests. Expose main(argv=None, *, send=transport, now=None, monotonic=..., sleep=...) for synthetic testing.

Strictly validate full schema3 base/catalog exact-byte hashes and every base CSV/date/OHLCV/count/identity/source/path before any HTTP. Both markets and every configured symbol required. Base cutoff must precede the new cutoff; source coverage/age and actual latest-allowed completed bars validated. File permissions700/600, no Git/private path escape/symlinks/hardlinks. Snapshot creation is exclusive and never overwrites an existing folder. Keep base bytes/hashes and recheck BEFORE final complete manifest.

For each configured symbol fetch one200-candle adjusted daily page bounded by new exclusive cutoff, using original normalization/completion semantics. Require ordered unique valid candles and endpoint/cursor validation. If fresh page has >=2 overlap dates and covers the base last date, compare ALL overlapping dates/OHLCV, require no missing base dates inside overlapping span. If exact overlap matches, retain base prefix and append only genuinely newer completed rows. Never fabricate dates or replace a mismatch with rescaling/interpolation. No-new-bar weekends can create a new correctly dated/lineaged snapshot, not invented bars. Validate resulting rows using unchanged legacy quality/split rules.

If any overlap disagreement or insufficient overlap, call original full history() for that symbol from declared start, SAME Auth/Client and remaining600/20min caps. This replaces the entire symbol in the NEW snapshot only, never the base. If unavailable/cap exhausted/stale/quality error/partial, preserve private failure/raw evidence and emit no complete manifest. Revalidate base hashes before fallback decisions and before publication.

Output schema3 uses root universe.json exact raw bytes and entries with ordinary safe CSV paths. Include explicit `provenance.refresh`: `policy: overlap200_prefix_carried_v1`, `base_manifest_sha256`, base provider/prepared_at/cutoff and per-symbol append/full-refresh/unchanged mode with first/last/row coverage. Keep original preparation/raw references private. This policy does NOT certify supplier revisions outside the200-bar overlap; older prefix retains its earlier acquisition vintage. No claim of canonical entire-history-as-of-today/PIT classification/total-return/calendar guarantee. First/last observed dates are not listing certification.

## Supervisor optional config

Add ONE optional `expanded_data` dictionary, strict exact fields:
- `universe_file`: absolute path under core_repo/universes; validated JSONv1/current falsePIT
- `universe_sha256`: exact64lowerhex digest (must also match code pin catalog)
- `seed_manifest`: absolute private path within THIS profile/private
- `seed_manifest_sha256`: pinned complete schema3 seed root digest
- `start_date`: `2000-01-01`
- `refresh_policy`: `overlap200_prefix_carried_v1`

Existing config schema1/default24 branch and LIMITS are unchanged. This optional dict is policy-hashed/canary-bound. Require code_pins include refresh_toss.py, universe_contract.py, collect_universe.py and the exact catalog along with original pins; never read credentials into logs. Collection CLI gets explicit base/catalog hashes and caps.

When starting a new day, choose the newest PRIOR complete acquisition snapshot from ledger entries under same private_root, SAME policy_sha256, strict date/cutoff before current date, and a stored `snapshot_sha256`. Do not depend on prior research accepting/finishing: completed data and failed research are separate. Validate candidate manifest/catalog hash/coverage before reuse. If a latest matching prior snapshot is corrupt, fail closed instead of quietly falling back. Ignore clearly incompatible older-policy legacy datasets without relabeling them. If none, use pinned seed. Preserve all prior ledgers/failed-start anchors/counters and daily acquisition_attempts=1. After successful acquisition bind `snapshot_sha256` in current day ledger before model launch; retain trusted seed and record lineage. Acquisition must be complete/frozen before research mode; no collection or mutable cache refresh by LLM.

Canary generation and exact binary/source/config/entry/workdir proof must match the new pinned revision; old synthetic registry can be inspected read-only with its original provenance. No source edits in activebc99433 checkout. Record today's real hypothesis/status and do not claim scheduled/research success from a synthetic canary.

## Evidence gaps

Separate current price availability from historical constituent/listing/delisting/suspension evidence. Gather authoritative public sources where available, with URLs/as-of semantics; missing historical knowledge must remain explicit unknown, never inferred from a continuous candle chain or backdated current tags. Do not buy/subscribe/contact external organizations or change trading risk. Existing #13/#28 stay open unless their actual criteria are met.
