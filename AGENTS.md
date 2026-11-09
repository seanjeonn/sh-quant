# Project Instructions

## Workflow

- Link work to a tracking issue before implementing, using the forms in `.github/ISSUE_TEMPLATE/`: `feature` for approved multi-step work, `bug-report` for a reproducible defect.
- Before finishing any task, file what it leaves behind as issues; a mention in chat is not a record. Use `work-proposal` for remaining, deferred, under-done, or nice-to-have work (set Source, link the originating issue under Related Work) and `bug-report` for bugs found but not fixed. Nothing left behind, file nothing.
- `gh issue create` does not render the forms: mirror the form's title prefix, label, and field headings in the body.
- Git/branch/release rules: see `docs/github-workflow.md`.

## Daily objective and modes

- The primary goal is **one complete strategy research set per Asia/Seoul day**, not one strategy file or one backtest. A set includes a preregistered hypothesis/experiment, a baseline, multiple parameter or meaningful strategy variants, development-only selection, final evaluation, conclusion, and next steps. Follow `docs/daily-research-set.md` and `hermes/SKILL.md`.
- **Research mode:** add new `strategies/*.toml`, the current set's `research/<set-id>/` artifacts, CLI-generated results/news, and completed backlog checkmarks. Do not change `src/`, `Cargo.*`, the dashboard, engine rules, pre-existing strategies/results, or another set's artifacts. The shared results index may gain the current set's entries via the CLI; existing entries must be preserved. Only the current set's own new result lessons may be updated.
- **Engineering mode:** implement approved, issue-linked changes to engines, data, dashboard, or tooling on a separate branch with tests and review. The engine is not globally off-limits to maintenance agents. Do not change it inside a research set to improve scores; pin engine/data provenance for comparisons and record any cross-version break.
- Protect the daily research objective. Review the engineering issue backlog weekly when automation is enabled; prioritize correctness/data/reproducibility blockers before enhancements. This is an operating policy, not evidence that a scheduler exists.
- Proposals are candidate work, not automatically approved features. Check issue bodies, comments, and active PRs before implementing; do not duplicate or overwrite another agent's work.
- `completed` means a supported accept/defer/reject conclusion after the full protocol. A negative result is valid; a data/execution/budget blocker is `blocked`, never a fabricated success. Do not mark a backlog item done until its set is completed.
- GitHub issue updates, working-branch pushes, and PR creation are approved for this project. Main merges/auto-merge, deployments/releases, force pushes/destructive operations, purchases, and live trading/orders/risk-limit changes require separate explicit approval. Never expose secrets in public artifacts.

## Project facts

- Build: `cargo build --release`; dashboard is static `index.html` (Vercel copies it + `results/` via `vercel.json`, no Rust build there).
- Test: `cargo test --locked`; research-rule contracts: `python3 -m unittest discover -s tests -p 'test_*.py'`.
- The signal DSL has no forward-looking operator and the engine also re-checks signals by truncating history. Paths resolve from `CARGO_MANIFEST_DIR`, so run from a checkout's root. `data/cache/` is gitignored, `data/news/` is committed.
- Current CLI supports `run`, `fail`, `lesson`, and `news` only. `run` computes/displays both IS and OOS; there is no implemented IS-only sweep, sealed holdout, research-set runner, or completion validator. Use the documented manual protocol, disclose OOS exposure, and track tooling gaps as issues. Research reports are not yet rendered by the dashboard.
