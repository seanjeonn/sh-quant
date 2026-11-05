# Project Instructions

## Workflow

- Link work to a tracking issue before implementing, using the forms in `.github/ISSUE_TEMPLATE/`: `feature` for approved multi-step work, `bug-report` for a reproducible defect.
- Before finishing any task, file what it leaves behind as issues; a mention in chat is not a record. Use `work-proposal` for remaining, deferred, under-done, or nice-to-have work (set Source, link the originating issue under Related Work) and `bug-report` for bugs found but not fixed. Nothing left behind, file nothing.
- `gh issue create` does not render the forms: mirror the form's title prefix, label, and field headings in the body.
- Git/branch/release rules: see `docs/github-workflow.md`.

## Project facts

<!-- Replace per project. Include only what cannot be inferred from the code. -->

- Build: none (stdlib only, Python 3.11+). Run with `python3 -m kingfish <run|backfill|repair|status>`.
- Test: `python3 -m unittest kingfish.test_kingfish -v` (no network).
- Gotchas: Toss allows one valid token per client — every process must share the token via the separate token DB `token_path` (`.kingfish-token.db`, 0600; never store it in the market data DB, never issue tokens elsewhere with the same key). Calls from IPs not on the WTS allowlist get 403. Candle `timestamp` is the bar END time; DB `ts` columns are UTC bar-end strings.

