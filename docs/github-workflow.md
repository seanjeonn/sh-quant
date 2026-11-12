# GitHub Workflow

## Issues, branches, and approval boundaries

- Follow `AGENTS.md` and the issue forms. Link approved multi-step work to a feature issue before implementing; use bug-report for reproducible defects and work-proposal for unapproved/deferred improvements. Search existing issues/PRs before writing.
- Use `research/<set-id>` for daily research and separate `feat/`, `fix/`, or `docs/` branches for engineering. Do not directly push main or combine engine modifications with a research set.
- The user approved project issue creation/updates, normal working-branch pushes, and PR creation. Do not treat a proposal label as implementation approval or opening a PR as completed integration.
- **Main merges/auto-merge, deployments, releases/tags, force pushes, destructive changes, purchases, and live trading/orders/risk-limit changes need separate explicit approval.** Do not enable auto-merge or publish a release on your own.
- Stage only named, scoped paths; inspect the diff for secrets/unrelated work. Research plan and candidate selection each need an immutable commit before the next phase described in `daily-research-set.md`.
- Read back exact remote issue/PR state, head SHA, and changed files after writes. Do not close a feature issue merely because a PR exists; use closing references for completion after an approved merge.
- A working-branch push may trigger existing preview CI/deploy hooks. Check repository/project settings when available; no production deployment or deployment configuration change is approved by this policy.
- Report local research completion, open PR state, actual checks, and main/deployment state separately. A scheduled cadence in prose is not an installed cron job.

## Release tagging

- **Only execute the tagging and push commands below after separate explicit approval that includes publishing the release tag.** Approval to open a PR or merge a non-release change is not release approval.
- When an approved release is merged into main, put a SemVer annotated tag on that merge commit: `vMAJOR.MINOR.PATCH` (e.g. `v1.2.0`).
- Create and push the tag:

  ```sh
  git tag -a vX.Y.Z -m "release vX.Y.Z" <merge-commit>
  git push origin vX.Y.Z
  ```

- Version bump: breaking changes are MAJOR, new features are MINOR, fixes or docs only are PATCH.
- Tag only released main commits. Do not tag ordinary, non-release merges.
