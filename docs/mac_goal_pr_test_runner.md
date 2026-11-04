# Mac Goal PR test runner

Run the focused Mac Goal-review tests for a GitHub PR with one command.

From the local `~/line-bot` checkout:

```bash
scripts/mac_goal_pr_test.sh 1255
```

Optionally pass a different pytest target:

```bash
scripts/mac_goal_pr_test.sh 1255 tests/test_mac_bonsai_goal_review_worker.py
```

The script:

1. Verifies that `origin` points to `nonkun12/line-bot`.
2. Fetches the PR head using GitHub's `refs/pull/<number>/head` ref.
3. Creates or safely updates the dedicated sibling worktree `../line-bot-goal-pr<number>`.
4. Refuses to overwrite an existing worktree with uncommitted changes.
5. Reuses the shared `../line-bot-media-pr1222/.venv/bin/python` when available, or checks other local Python candidates. Set `PYTHON` to override.
6. Runs pytest and saves the full output under `~/Library/Logs/line-bot-goal-pr-tests/`.

Exit code 0 means pytest passed; a nonzero exit code means failure. The script does not edit source files, push branches, merge PRs, or deploy services. GitHub Actions status remains a separate check; a local PASS does not imply CI PASS.

## Prerequisites

- macOS with Git and Python installed.
- The current checkout is the `nonkun12/line-bot` repository.
- The selected Python environment has pytest and the project's test dependencies installed.
