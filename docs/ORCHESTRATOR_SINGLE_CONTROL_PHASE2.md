# Orchestrator Single-Control Migration — Phase 2

## Decision

All four former sub-systems remain closed. The Orchestrator is the only future
control plane. This document defines the read-only integration boundary; it
does not restart any workflow or authorize task execution.

## Verified source snapshot (2026-11-15)

The repository snapshot below was inspected read-only on 2026-11-15; these counts are point-in-time evidence, not live dashboard values:

- `.github/autonomous-loop-tasks.json`: 4 queued entries.
- `.github/autonomous-loop-task-catalog.json`: 71 unique catalog entries.
- `autonomous-loop-state:.autonomous-loop-state.json`: 54 completed IDs and
  73 Recovery AI task records.
- Catalog overlap: 34 completed, 37 held, 1 review-required, 0 eligible under
  the current completed/held/review rules.
- All four entries in the current runtime queue are already completed; one
  also carries `resume_requires_review=true`.
- `.autonomous-loop/free-deterministic-queue.json` is empty.

These are different queue sources and must not be conflated. The free pilot
queue is not the same file as the legacy distributed LOOP queue.

## Required read-only adapter contract

The adapter may read only:

1. The active runtime queue.
2. The reviewed task catalog (allowlist).
3. The durable state branch snapshot.
4. An independently sourced budget evidence document.
5. A separately verified Global HOLD / kill-switch state.

It must reject missing, malformed, stale, duplicate, or cross-source-mismatched
records. It must not refill a queue, resurrect completed tasks, release HOLD,
or infer approval.

Each output task must retain its source identity and classification:
`pending`, `completed`, `held`, or `review_required`. Completed, held, and
review-required tasks are never candidates.

## Approval and budget boundaries

- `execution_approved: true` in a queue JSON file is caller-supplied metadata,
  not proof of human approval.
- A future approval verifier must check a durable, immutable record bound to
  the exact Task ID, task definition digest, approver identity, timestamp, and
  expiry/revocation status.
- The 2,000-minute value is only a hard ceiling. It is not proof of remaining
  quota or actual usage.
- Budget evidence must include source, observation time, consumed minutes,
  reserved minutes, and a freshness bound. Missing or stale evidence means
  execution remains blocked.
- Schema validity and freshness alone do not authenticate a JSON evidence file.
  Until a cryptographic/provenance verifier is implemented, even a well-formed
  Global HOLD=false or budget snapshot remains unverified and the gate stays
  BLOCKED.
- The Orchestrator planner always reports
  `execution_authorized=false`; it only produces a plan.

## Global HOLD and permissions

- Missing or unverifiable Global HOLD state is treated as HOLD.
- A kill switch, explicit HOLD, or malformed state blocks all candidate
  execution.
- The plan-only workflow must use read-only repository permissions and must
  not invoke `distributed-autonomous-loop.yml`.
- No Actions dispatch, issue/PR write, branch write, push, merge, deploy, or
  approval mutation is part of Phase 2.

## Legacy LINE route closure

The application entry point now calls the legacy distributed-loop trigger with
dispatch disabled. Start commands for the old loop return a closed-route
message and do not call the GitHub Actions dispatch API. The Recovery AI
resume-review acknowledgement route is also disabled from LINE while the
single-control migration is in progress. Neither route can clear HOLD or
change review state. Historical old-loop status is labeled as legacy evidence
and must not be presented as current Orchestrator activity.

## LINE integration contract

LINE requests are split into two strict classes:

- Read-only: status, queue summary, plan preview, blocker explanation.
- Mutating: enqueue, approve, resume, execute, create PR, merge, deploy.

Phase 2 exposes only read-only requests. Mutating requests return a clear
"not enabled" response and do not fall through to legacy dispatch functions.
The old four sub-system routes remain closed.

## Phase 2 acceptance gates

1. Read-only adapter validates all source identities and state freshness.
2. Empty/ineligible queue returns `NO_TASK` or `HOLD`, never a fabricated task.
3. Completed/held/review-required tasks cannot re-enter the candidate set.
4. Approval and budget evidence are independently verified or execution is
   explicitly unauthorized.
5. Global HOLD uncertainty fails closed.
6. CLI and dashboard output source counts, timestamps, blocker codes, and
   `execution_authorized=false`.
7. Unit tests cover malformed input, stale state, duplicate IDs, mismatched
   task definitions, held/completed exclusion, and missing evidence.
8. LINE read-only status/plan routing has E2E tests proving no dispatch call.
9. No former sub-system workflow is re-enabled.
10. A human-reviewed trial report records `NO_TASK`, `BLOCKED`, or a plan
    result without executing work.

## Current gate result

**NOT READY FOR EXECUTION.** The catalog currently has zero eligible tasks,
the active runtime queue contains only completed entries, and the durable
state does not provide independently verified budget or approval evidence.
The next safe test is a plan-only snapshot, not a worker run.
