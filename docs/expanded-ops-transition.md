# Expanded-data operating transition (#61)

## Authorization and boundaries

User approval1570986971021582459 covers the remaining PR58 main integration, #60 refresh implementation and verified operating transition, plus investigation of #13/#28 historical evidence. PR58 is now merged at e9503207085344ca43ce90a913318bde5b24b565. This is not permission for paid data, account/order APIs, live trading/risk changes, force pushes, releases or unrelated deployments.

Active operating source remainsbc99433 until new-path tests, actual bounded refresh/native input, independent review and generation-specific actual canary pass. The original daily14:30/continuation/deadline/weekly schedules and all600request/20min/4launch/120min/17:00caps are retained. See [expanded-refresh-contract.md](expanded-refresh-contract.md).

## Data policy, not a false full-history guarantee

The canonical96/current-selected catalog and its hash are fixed. A day refresh compares one200-bar completed daily page per instrument with the validated cached tail. Exact overlap permits a carried older prefix plus new rows. Any mismatch/no usable overlap triggers that instrument's full-history fetch within the SAME600/20min budget; insufficient budget blocks the entire snapshot. No base file is overwritten, no names are dropped, no price rescaling/interpolation is used. The snapshot records per-symbol history vintage and lineage. Provider corrections strictly outside the overlap are not certified detected; archival provider-history audits are a separate bounded data-version operation, not a promise of canonical whole-history-as-of-today.

Historical membership/inception/delisting/suspension completeness remains evidence-driven. Current themes are manual and PITfalse; an observed first candle is not a listing certificate. Free official-source findings and missing evidence must be linked, not synthesized or silently accepted.

## Transition gates (parent-owned)

1. Approved feature61 is the implementation tracker, sourceproposal60. Preserve old config/jobs/guarded entries, old binary/source locations and original immutable data/receipt/registry hashes before changes. Never edit another profile or active operating source.
2. Parent runs full Python/Rust/offline release checks, adversarial partial/mismatch/budget/base-corruption cases and independent review. A private actual refresh pilot must validate all96 within unchanged daily caps, base-before/after/raw/CSV/catalog hashes and native frozen input. Preserve even failed pilots and do not rename outputs to hide failure.
3. Integrate reviewed code into main under the user's approval and required CI without bypass. Freeze an exact dedicated operating checkout/revision; verify source/binary/catalog/config pin equality. Subsequent docs/evidence commits must not move that operating checkout. All later operation evidence can be saved privately and in issue comments without changing its HEAD.
4. Before switching, require no current-day ledger/in-flight worker and verify the real current KST time. Pause only the intended jobs for the short switch; back up and render guarded entries' fixed checkout literal while retaining all ownership/profile/hash/private guards. Set the new optional expanded_data config and fresh generation/nonce, activationfalse. Read back exact config/jobs/entries and exercise idle continuation without day initialization.
5. Fire the existing far-future canary once through actual cron/model (temporarily resume only if the installed runtime requires it; immediately pause future canary scheduling). Consume its callback, do not poll/retry while pending. Validate private receipt/policy/source/log hashes, unchanged synthetic attempts, actual Discord nonce message identity and restored paused canary state.
6. Only then activationtrue and recurring jobs resume. Read back timezone/workdir/scripts/delivery/enabled/next-run values and actual host ticker. This establishes configured/tested/scheduled state, not a completed research day.
7. Let the normal14:30 daily acquire the correctly dated96 snapshot, preregister a bounded hypothesis, execute distinct baseline/variants, freeze IS selection and evaluate exposed OOS. Verify actual source/data scope, immutable runner attempts/checkpoints, exact remote PR/blob publication and conclusion. Protect today's complete research loop from infrastructure work.

## No unsafe rollback across an experiment boundary

Before a day ledger or real daily acquisition exists, an unsuccessful entry/canary transition may restore the exact old config/entries/job settings with an audit trail while preserving failed evidence. It is not permission to bypass a tool-denied write. After a current-day ledger/acquisition exists, do not swap policy, delete state or reset its epoch/counters to make it run under another version. Keep the evidence, investigate and explicitly report blocked/incomplete when required. Historical audits use the original config/revision context; do not re-label old trials with new hashes.

If implementation/validation has not finished safely before today's normal start, retain the original scheduled research path for that day; defer migration across the next clean version boundary rather than interrupting or duplicating an in-flight set. Report any source/data blocker honestly; never mark a data blocker as a strategy rejection.
