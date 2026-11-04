# Mac Goal PR batch test runner

Run the focused Mac Goal-review tests for multiple PRs with one command.

From a local checkout of `nonkun12/line-bot`:

```bash
bash scripts/mac_goal_pr_batch_test.sh 1251-1255
```

You can also list PRs explicitly or combine ranges:

```bash
bash scripts/mac_goal_pr_batch_test.sh 1253,1254,1255
bash scripts/mac_goal_pr_batch_test.sh 1251-1253,1255
```

To use a different pytest target:

```bash
bash scripts/mac_goal_pr_batch_test.sh 1251-1255 tests/test_mac_bonsai_goal_review_worker.py
```

The batch runner calls the existing `mac_goal_pr_test.sh` for each PR. It fetches each PR head, uses its dedicated sibling worktree, reuses the configured Python environment, runs pytest, and applies the existing per-PR newest-five-log retention policy.

- Runs sequentially, not concurrently, to avoid resource contention on the Mac.
- Continues to the next PR after a test failure.
- Prints a final per-PR PASS/FAIL summary.
- Exits 0 only when every selected local pytest run passes.
- Accepts ascending ranges of up to 50 PRs per range.
- Does not edit project source, push, merge, deploy, or delete worktrees or virtual environments.
- A local PASS is not a GitHub Actions CI result; CI must still be checked separately.

The single-PR runner remains available for targeted checks.
