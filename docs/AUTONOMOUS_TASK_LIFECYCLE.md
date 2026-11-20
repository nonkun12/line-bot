# Autonomous task lifecycle

This document describes the separate approval gates from review candidate discovery
through execution and feedback. No stage implicitly grants the next stage's authority.

## 1. Discover a review candidate

The distributed loop may produce a bounded review-only candidate and publish a GitHub
Issue. The Issue is not a queue entry. Its body states that queue admission is not
authorized and that execution approval has not been granted.

## 2. Approve catalog registration

A repository owner reviews the Issue and applies the
`autonomous-task-catalog-approved` label while retaining
`autonomous-task-candidate`. The registration workflow validates the source
fingerprint, exact test-only path, current source/test contents, and Recovery AI state.
It creates a draft catalog-registration PR with `execution_approved: false`.

A human reviews and merges that PR. This approval only registers the task in the
catalog; it does not authorize execution.

## 3. Grant execution approval separately

Execution approval is a distinct human decision. In a separate catalog change, a
repository owner may set the exact registered entry's `execution_approved` field to
`true`, after reviewing the task definition and its allowlisted test path. Do not
combine this decision with the registration change.

The refill process ignores entries unless `execution_approved` is exactly boolean
`true`. HOLD, completed, and resume-review-required tasks remain ineligible.

## 4. Prepare a read-only execution approval manifest

After the catalog change is merged to `main`, run the
**Prepare Autonomous Task Execution Approval** workflow on `main` and provide the
exact task ID. The workflow rebuilds the eligible queue from the catalog and durable
state, then verifies the selected task definition, execution approval, one-task limit,
base commit, completion state, and Recovery AI HOLD/review flags.

The output contains the exact values for a later manual dispatch:

- `task_id`
- `approval_instruction_sha256`
- `approval_allowed_paths_sha256`
- `approval_base_sha`
- `max_tasks=1`
- `execution_approval=APPROVE_EXECUTION`

This workflow has read-only repository permissions. Its manifest explicitly records
`execution_authorized: false` and requires a human dispatch. It does not modify the
catalog, queue, durable state, Issues, PRs, or branches.

## 5. Dispatch exactly one task

A human must separately dispatch **Distributed Autonomous Development Loop** on
`main`, copying the manifest values into the matching inputs and selecting
`execution_approval=APPROVE_EXECUTION`, `mode=normal`, and `max_tasks=1`.

The runtime independently rechecks the sender, repository, default branch, exact
task ID, catalog execution approval, queue/catalog definition equality, instruction
digest, path digest, base SHA, kill switch, REA evidence, Recovery AI, and Control
Tower. The one-shot execution approval marker is consumed by the guarded runtime
immediately before execution. A mismatch, missing evidence, active HOLD, or reused
approval fails closed.

## 6. Verify result and feed self-improvement

A result is eligible for task-history learning only when the task ID is registered and
the result status is `PASS` or `NO_CHANGE`, with successful publish and durable-state
gates. Verified failures are recorded only under the existing sanitized failure rules.
A run-level cycle memory is appended idempotently. REA security/evidence outcomes are
stored separately in `rea_observations`; they are never relabeled as developer task
failures.

The next review-candidate pass may use the sanitized task and REA histories to propose
bounded review-only improvements. This does not grant execution approval.

## Authority boundaries

| Stage | Human decision required | What it grants |
| --- | --- | --- |
| Candidate Issue | Review candidate | Review visibility only |
| Catalog registration | Catalog-approved label + PR review/merge | Catalog entry with execution approval false |
| Execution approval | Separate reviewed catalog change | Eligibility for one-task approval preflight |
| Runtime dispatch | Explicit task-bound workflow dispatch | One exact task execution attempt |
| Publication | Independent runtime, REA, path, and state gates | Verified development branch publication only |
| Merge/deploy | Separate human authorization | Not granted by this lifecycle |

No automatic merge, deployment, HOLD release, or permission change is part of this
flow. The lifecycle is intentionally not a hands-free execution loop: human approval
is required at the catalog and execution boundaries.
