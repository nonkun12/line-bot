# Orchestrator Core (Phase 1)

The provider-free Orchestrator Core is a deterministic planner for the free
GitHub Actions LOOP. It is intentionally separate from the existing
free-deterministic-loop runner.

## Responsibilities

- Validate the task registry and dependency graph.
- Detect missing dependencies, duplicate IDs, and dependency cycles.
- Respect task states, global HOLD, explicit per-task execution approval,
  and a hard 2,000-minute budget ceiling.
- Produce a deterministic candidate order (priority descending, then ID).
- Emit a read-only plan with explicit evidence that no execution or mutation
  occurred.

## Input contract

See `.autonomous-loop/orchestrator-queue.example.json`. Runtime state and
budget figures must be supplied explicitly. Unknown or malformed values fail
closed; this module does not infer approvals or available budget.

## Run

```sh
python scripts/orchestrator_core.py \
  --input .autonomous-loop/orchestrator-queue.example.json
python -m unittest tests.test_orchestrator_core -v
```

## Phase 1 safety boundary

A selected candidate is a planning result, **not dispatch authorization**.
This module does not invoke workers, Actions APIs, LLMs, external providers,
Git operations, PR creation, merge, or deployment. Existing pilot runner
behavior is unchanged. The 2,000-minute ceiling is a configured safety cap,
not a statement of GitHub quota entitlement or usage.
