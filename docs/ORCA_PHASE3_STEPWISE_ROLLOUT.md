# Orca Phase 3: Step-by-step rollout

## Operating rule

Phase 3 is introduced one step at a time. A step is not accepted until its
implementation, focused tests, full test suite, and independent review pass.
A failed or unverifiable prerequisite stops progression. No later step is
enabled by a previous step's test result alone.

Global safety defaults remain:
- Global HOLD is fail-closed.
- One task maximum per run.
- No automatic patch application, merge, deployment, or schedule activation.
- No paid API, paid inference, paid cloud fallback, or usage-based service.
- Missing budget, approval, evidence, or state is BLOCKED.
- Draft PR only; production state is not initialized or modified.

## Step 3-A — Unified execution gate

**Purpose:** Validate the queue, Global HOLD, task identity and hash, signed
short-lived task approval, replay ledger, trusted GitHub Actions budget
evidence, and recursive-improvement evidence before any claim.

**Acceptance:** Focused gate tests, whole pytest, Orca status tests, syntax
checks, and independent review pass. The gate itself is pure validation and
must never execute a task.

**Boundary:** A code-level PASS is not permission to run. The trusted budget
collector and LINE approval-signing/identity source must be connected and
independently verified before live use.

## Step 3-A2 — Atomic approval consumption + single-task claim

**Purpose:** In one state-store compare-and-swap commit, append the approval
ID to the durable replay ledger and transition exactly one queued task to
claimed with a lease. A stale ref or any gate failure must abort without
claiming. The worker must not start in this step.

**Acceptance:** Tests prove one write contains both the replay marker and
lease, rejected gates write nothing, duplicate approvals write nothing, and
stale-ref conflicts are not retried against stale state. The state store must
use a non-force fast-forward update and verify the read-after-write snapshot.

**Boundary:** A successful claim is still not task execution. No worker is
dispatched or invoked by the coordinator.

## Step 3-B — Worker dry-run only

**Purpose:** Add a single-task worker path that consumes a previously claimed
task envelope but performs no external side effects. It validates task type,
input bounds, run/lease ownership, and the execution-disabled default, then
emits a deterministic dry-run report.

**Acceptance:** No subprocess, external API, repository mutation, PR, deploy,
or user-data write occurs. Tests cover malformed envelopes, missing lease,
expired lease, duplicate run, and Global HOLD.

## Step 3-C — Recovery and adversarial tests

**Purpose:** Verify crash between claim and completion, lease expiry, stale
writer races, replay, retries, duplicate delivery, malformed evidence, budget
staleness, and approval expiry.

**Acceptance:** Every ambiguous or unsafe condition ends in BLOCKED/HOLD;
there is no double claim and no silent retry that bypasses fresh validation.

## Step 3-D — Independent review

**Purpose:** Request a separate safety review of the exact tested commit and
its diff. Resolve Critical/High findings and re-run affected tests.

**Acceptance:** No unresolved Critical or High issue; reviewer verifies that
the code path remains fail-closed and does not enable execution implicitly.

## Step 3-E — Explicitly approved non-production single-task trial

This step is not automatic. It requires a separate explicit user approval
after the preceding steps pass, verified trusted budget evidence, verified
LINE approval identity/signing, provisioned state with Global HOLD semantics,
and a documented rollback path. Limit to one approved task and observe the
result before considering any cadence.

## Step 3-F — 30-minute cadence (separate approval)

Schedule activation is a separate decision and is not included in Phase 3-A
through 3-D. Before activation, verify free GitHub Actions quota headroom,
budget evidence freshness, monitoring, kill switch, and rollback. Do not
enable the schedule without explicit user approval.

## Current checkpoint

- Step 3-A gate: implementation present; latest full test suite and focused
  Orca status checks passed at commit `162b20fa15977545458fcda7322fc8e8a9dd93ce`.
- Step 3-A2: atomic approval-consumption + single-task claim coordinator added; syntax, independent review, whole pytest, and Orca status checks passed at commit `afca1797d8e425bfe7e6063fa4c7aba45e61951e`.
- Step 3-B: side-effect-free single-task worker dry-run added; validates Global HOLD, exact envelope shape, canonical payload hash and size, claimed task, lease ownership/run, and lease expiry. It does not execute task code or perform side effects. Syntax, independent review, full pytest, and Orca status tests passed at commit `3767eff73d365215ebe60e0b9e4804fec49d7aaa`.
- Step 3-C: crash/recovery, duplicate delivery, expired lease, reclaim fencing, Global HOLD after claim, stale worker, and double-finish adversarial tests added; CI pending.
- Steps 3-D onward: not started.
- Trusted budget collector and LINE approval identity/signing integration:
  not connected; live execution remains blocked.
- State branch is not provisioned; no schedule is enabled.
