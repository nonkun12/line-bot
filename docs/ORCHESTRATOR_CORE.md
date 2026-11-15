# Orchestrator Core (Phase 1)

The provider-free Orchestrator Core is a deterministic planner for the free
GitHub Actions LOOP. It is intentionally separate from the existing
free-deterministic-loop runner.

## Responsibilities

- Validate the task registry and dependency graph.
- Detect missing dependencies, duplicate IDs, and dependency cycles.
- Respect task states, global HOLD, caller-supplied approval metadata,
  and a hard 2,000-minute planning ceiling.
- Keep planning eligibility separate from execution authorization.
- Produce a deterministic candidate order (priority descending, then ID).
- Emit a read-only plan with explicit evidence that no execution or mutation
  occurred.

## Input contract

See `.autonomous-loop/orchestrator-queue.example.json`. Runtime state and
budget figures must be supplied explicitly. Unknown or malformed values fail
closed; this module does not infer approvals or available budget.

The JSON input is a caller-supplied snapshot, not a live or durable task
ledger. The example queue is illustrative and is not connected to the
production LOOP queue. No task state is written back by this phase.

The `execution_approved` boolean is untrusted caller metadata. It is shown
for planning context only; it is not an approval credential. The planner
always emits `execution_authorized=false`,
`approval_evidence_verified=false`, and
`budget_evidence_verified=false`. A future execution gate must independently
verify an immutable approval record and authoritative usage evidence before
any dispatch. A planning candidate must never be interpreted as permission
to run.

## Run

```sh
python scripts/orchestrator_core.py \
  --input .autonomous-loop/orchestrator-queue.example.json
python scripts/orchestrator_dashboard.py \
  --input .autonomous-loop/orchestrator-queue.example.json
python -m unittest tests.test_orchestrator_core -v
```

The dashboard prints a Markdown snapshot to stdout. It does not create output
files, call GitHub APIs, persist state, dispatch work, or authorize execution.

## Phase 1 safety boundary

A selected candidate is a planning result, **not dispatch authorization**.
This module does not invoke workers, Actions APIs, LLMs, external providers,
Git operations, PR creation, merge, or deployment. Existing pilot runner
behavior is unchanged. The 2,000-minute ceiling is a configured safety cap,
not a statement of GitHub quota entitlement or usage.
