# Actual expanded-data validation — feature #57

This record is availability/integrity metadata, not investment performance. Raw provider responses, candles, detailed private paths, metrics and curves are not published.

## Observed acquisition

- Catalog: thematic_v1, **96 instruments**, US48/KR48;31 manual present-day research tags.
- Requested start2000-01-01, exclusive cutoff2026-11-13.
- Actual US aggregate date extent2000-01-03–2026-11-12;268,162 rows. KR aggregate date extent2000-01-04–2026-11-12;262,351 rows.
- Total **530,513 rows**; every configured instrument is present and every observed last date is2026-11-12. Individual first dates vary; the latest observed start in this cohort is2019-03-05. An observed first date is not a certified listing date.
- Actual2,703HTTP requests, all recorded successful responses;8 complete batches. Pessimistic reserved charge4,800 of the6,000-attempt cap; no refunds/reset. Root acquisition completion was961.763seconds after the fixed initial epoch, inside120minutes.
- Independent parent validation checked every CSV count/date/price bound/hash and every retained request raw hash, exact configured identity/order, batch descriptors/receipts and root provenance. All original attempts remain private.

## Native/regression verification

- Actual native schema3 frozen canary executed on this complete input with a prespecified constant always-long engineering signal, NEW private output ID, no alpha selection. Successful native execution and final frozen-input verification observed.
- Separately, old pinned binary and new binary produced **exactly identical actual US/KR metrics and curves on the same legacy24 frozen input**. Original input contents stayed unchanged. Numerical evidence remains private.
- Explicit resume of this completed initial acquisition returned success with byte-identical root manifest and unchanged attempt inventory/receipts: no requests, new batch launches or successful-batch re-downloads.
- Parent full Python179PASS, Rust30PASS/1helperignored, releasebuild; independent reviews2APPROVE and Ubuntu required CI succeeded on code commitb6b1ee0. Later metadata-only report commits do not alter collection source.

## Immutable identities

- Root manifest SHA256: `a19957c23f8931ccb6d2588529bb22559a544a64c6d6b7bcae45a9a8fb15f231`
- Catalog raw-byte SHA256: `140b31ef0309503a1d7e418059f3d82cc5ac39476eaf8269cb68db9a3f6d8e86`
- Native canary binary SHA256: `c1d786015838a3897cdf9139b7cc682ada7b43c93040201e09e2b36113044f46`
- Verification source commit: `b6b1ee0f1bb8c8d3791191405b4ab5f9df4ae894`

## Limitations / rollout

Current-selected survivors and current2026-11-13 classifications are **not point-in-time historical membership**. Present tags must not be used as past trading signals. No reconstruction of delisted constituents or historical ETF holdings is certified; #13 remains. Calendar completeness, suspensions, corporate-action/total-return semantics remain #28. Samples begin only where provider data exist; no pre-inception rows were created. KR equities and US mixed ETF/equity pools are compositionally different, with overlaps and unequal theme representation; unchanged native equal-symbol weighting is not theme-balanced allocation.

This is a completed **engineering dataset validation**, not another strategy research set or an alpha result. PR58 is not main merge or operating migration. Active daily pinbc99433 and its original24-symbol/default2015 collection are unchanged. A wider daily-data refresh/eligibility/freshness contract and new-version canary must precede operating adoption, without silently increasing the existing600request/20minute acquisition cap. See #57 and operating-transition proposal #60.
