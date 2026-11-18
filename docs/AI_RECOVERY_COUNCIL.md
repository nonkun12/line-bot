# AI Recovery Council

This feature adds a local-first, fail-closed repair runner. It is intentionally
not wired into scheduled GitHub Actions: a hosted runner cannot reach a user's
loopback-only local model, and no cloud or paid fallback is permitted.

## What it does

1. Accepts a structured failure record and discards arbitrary fields.
2. Asks a loopback-only OpenAI-compatible local model for up to two small patches.
3. Sends each proposal to a critic pass and requires an explicit `ACCEPT`.
4. Validates patch paths, file count, changed-line budget, and focused test names.
5. Applies a candidate only on a clean `ai-repair/*` branch.
6. Runs `git diff --check` and the selected existing pytest files.
7. Rolls the patch back if validation or a focused test fails.
8. After failed attempts, asks the model for a revised proposal, for at most two rounds.

## Scope and limits

- Patch targets are restricted to existing tracked files below `scripts/` and
  `agents/english/`. Safety, approval, control, recovery, auth, workflow,
  deployment, secret, and critic-related paths are denied.
- Existing tests cannot be edited by the model. Tests must already exist under
  `tests/test_*.py`; shell commands are never accepted.
- The runner never commits, pushes, opens PRs, clears HOLD, merges, or deploys.
- A passing patch remains uncommitted in the dedicated repair branch for review.
- Proposal-only mode may use one local model for both roles. Applying a patch
  requires a second loopback endpoint and a different critic model identifier
  (AI_REPAIR_CRITIC_MODEL_URL, AI_REPAIR_CRITIC_MODEL). The runner still records
  critic_independent=false because it cannot attest the actual loaded model
  weights or runtime identity.
- Passing focused tests is not proof of long-term effectiveness. The report
  records `effectiveness=NOT_MEASURED`.
- If the local model is unavailable, the runner stops. It does not use a remote
  API, hosted model, or paid fallback.

## Run

Configure an OpenAI-compatible server bound to loopback and set the actual model
identifier exposed by that server:

```sh
export AI_REPAIR_MODEL_URL="http://127.0.0.1:8081/v1"
export AI_REPAIR_MODEL="your-local-model-id"
export AI_REPAIR_CRITIC_MODEL_URL="http://127.0.0.1:11434/v1"
export AI_REPAIR_CRITIC_MODEL="your-distinct-critic-model-id"
python -m scripts.ai_repair_runner \
  --evidence /path/to/sanitized-failure.json \
  --output artifacts/ai-repair/report.json
```

The command above generates proposals only. To apply and test a candidate, first
create and check out a dedicated clean branch named `ai-repair/<task-id>` from main,
then run the same command with `--apply`. For example:

`git switch main && git pull --ff-only && git switch -c ai-repair/<task-id>`

The repository must be clean before the runner starts. Review the resulting diff before committing or publishing it.

## Completion status

The runner and policy tests are present on the feature branch. They have not yet
been executed in this environment, and the runner is not yet connected to the
30-minute distributed loop, STAR-NIGHT, or English Core Words workflows.
