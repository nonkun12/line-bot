# AI Control Capability Ledger

Last verified: 2026-10-16
Repository: `nonkun12/line-bot`

This ledger records observed integration capabilities, not assumptions about GitHub account permissions.

## Verified in the current ChatGPT GitHub connection

| Capability | Evidence / boundary |
|---|---|
| Read repository files and blob SHAs | `fetch_file` successfully read the workflow, loop runner, queue, and tests. |
| Inspect workflow runs and jobs | Workflow-run/job retrieval tools are available. |
| Read workflow job logs and artifacts | Job-log and artifact retrieval tools are available. |
| Create branches, files, issues, and pull requests | Corresponding write tools are available; use a branch and reviewable PR for code changes. |
| Comment on an issue or PR | Comment tools are available. A PR comment can trigger the repository's allowlisted `issue_comment` workflow path. |
| Re-run failed workflow jobs | A failed-job rerun operation is available; it is not equivalent to starting a new workflow run. |
| Start a new workflow via a dedicated `workflow_dispatch` connector operation | **Not exposed in the tool catalog checked on 2026-10-16.** This is a connector-operation gap observed in this session, not proof that the GitHub account lacks permission. |

## Safe launch alternatives

1. Prefer the repository's explicit, bounded trigger on an authorized PR comment:
   - `/distributed-loop max_tasks=1` through `/distributed-loop max_tasks=4`.
   - The workflow validates the exact comment body and collaborator association.
2. Use the GitHub Actions UI for `workflow_dispatch` when a specific dispatch input is required (for example, resuming a held task with explicit cause-fixed confirmation).
3. Do not treat re-running a failed job as equivalent to dispatching a fresh run.
4. Before claiming launch, retrieve the resulting run ID and verify its task-level outcome. A green workflow conclusion can still contain `BLOCKED`, `NOT_RUN`, or zero executed tasks.

## Safety invariants

- Never clear held-task state merely to make a run proceed.
- Never infer a successful task from a successful workflow conclusion or a Sheets `RECORDED` marker.
- Verify task IDs, task result evidence, changed paths, produced SHA, post-run gates, and LINE `sent` status separately.
- Keep `AUTO_APPLY_PATCH=false` and `AUTO_DEPLOY=false`; no automatic merge or deployment.
