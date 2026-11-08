# Human-gated autonomous task registration

This flow separates three independent decisions. None is inferred from another.

1. **Candidate** — an issue labeled `autonomous-task-candidate` records a proposed test-only task. It is not executable.
2. **Catalog registration** — the repository owner manually dispatches **Register Autonomous Task (Human Review)** with the issue number entered twice. The workflow validates the candidate and creates a PR that changes only `.github/autonomous-loop-task-catalog.json`.
3. **Execution approval** — only after the catalog PR is reviewed and merged may a human separately review the source issue and apply `autonomous-task-execution-approved`. Keep `autonomous-task-candidate` on the issue. The proposal generator requires both labels and an exact match of task ID, instruction, and allowed paths against the merged catalog. It continues to exclude completed, held, and review-required task IDs.

**Important label distinction:** `autonomous-task-approved` is a legacy/catalog-registration label and does not authorize queue admission. The execution queue recognizes only `autonomous-task-execution-approved` together with `autonomous-task-candidate` and an exact registered catalog match.

## Safety properties

- The registration workflow runs only when `github.actor == github.repository_owner`.
- The confirmation input must exactly match the issue number.
- The source issue must be open and candidate-only; an issue already carrying the legacy `autonomous-task-approved` label is rejected.
- The embedded spec must contain exactly `id`, `instruction`, and one `tests/test_*.py` allowlisted path.
- Duplicate, completed, queued, or already-known Recovery AI task IDs are rejected.
- The workflow creates a pull request; it does not merge it, apply the execution-approval label, modify runtime queue/state, or dispatch the distributed loop.
- The distributed loop remains fail-closed unless the separately approved issue exactly matches the merged catalog entry.

## Operator procedure

1. Review the candidate issue's source evidence, existing test coverage, instruction, and single allowed test path. Confirm it has the `autonomous-task-candidate` label.
2. Open **Actions → Register Autonomous Task (Human Review) → Run workflow** on `main`.
3. Enter the candidate issue number in both inputs and run the workflow.
4. Review the generated catalog-only PR and its CI. Merge it only after review.
5. Re-open the source issue and confirm its embedded spec still exactly matches the merged catalog entry. Apply `autonomous-task-execution-approved` as a separate human action; do not substitute `autonomous-task-approved`.
6. Run the distributed loop with a one-task limit and inspect the task result, SHA, changed files, tests, and review evidence.

If any validation fails, stop and repair the candidate or state through a reviewed change. Never clear HOLD or `resume_requires_review` as a shortcut.
