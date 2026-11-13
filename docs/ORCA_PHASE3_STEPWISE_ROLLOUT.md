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

## Human Emergency Stop (terminal + LINE)

Both entrypoints latch the same durable `emergency_stop=true` field in the
GitHub-native state document using the state store's non-force CAS write.
The stop is checked before atomic claim and at the worker boundary. There is
no automatic clear/reset path; clearing requires a separately reviewed,
explicit human recovery procedure and audit trail.

Terminal command (requires the configured GitHub state-store environment):

```sh
python -m scripts.orca_emergency_stop --reason "operator requested emergency stop"
```

LINE exact command examples:

- `緊急停止`
- `緊急停止: 暴走の兆候`
- `ORCA STOP`
- `EMERGENCY STOP`

LINE must use the configured authorized-user allowlist. If the allowlist,
GitHub token, state branch, or state document is unavailable, the request
must be reported as not durably recorded and execution remains fail-closed.
The LINE webhook must call the shared handler only after validating the
platform webhook signature; user ID alone is not proof of message origin.

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
- Durable free-only anti-runaway guard: one task and one attempt per run, 30-minute run ceiling, two-failure circuit breaker, one-hour minimum cooldown, paid services disabled, and automatic retries disabled. The guard is consumed atomically with the claim and rechecked at worker start.
- Human Emergency Stop: shared terminal and LINE entrypoints now route to the same durable STOP latch. Terminal command is `python -m scripts.orca_emergency_stop --reason "暴走の兆候を検知"`; LINE aliases are `緊急停止`, `緊急停止: 理由`, `ORCA STOP`, and `EMERGENCY STOP`. LINE handler is prioritized before other AI/development routes and requires the configured user allowlist; LINE webhook signature validation remains in the existing SDK callback path.
- Terminal/LINE Emergency Stop focused tests added; syntax and independent review passed on intermediate commits; full pytest and Orca focused tests pending for the latest head.
- Steps 3-D onward: not started.
- Trusted budget collector and LINE approval identity/signing integration:
  not connected; live execution remains blocked.
- State branch is not provisioned; no schedule is enabled.

## Verified checkpoint — 2026-11-13 (PR #1354)

This checkpoint supersedes older pending/optimistic statements above.

### Step 1 — CI and recovery evidence
- Commit `f02c1e280be42a8b6589c2fcff2970812543daf2`: Python syntax scan, Orca status focused tests, and full Pytest all completed successfully.
- The prior stale assertion expecting `proposal_only` was changed to expect `blocked`; the corrected branch head is green.
- The test suite passing does not prove a live worker or live cadence.

### Step 2 — independent review
- The workflow named “AI Code Review” completed successfully, but its recorded job steps only set up the job, check out the repository, collect changed files, and show the diff. It is not evidence of an independent semantic/safety review.
- A separate review of the exact head remains required. Do not mark Step 3-D accepted based on that workflow status.

### Step 3 — worker boundary
- `scripts/orca_github_worker_dry_run.py` validates the queue state, STOP/HOLD, envelope, payload hash/size, lease, and runaway guard, then returns `DRY_RUN_PASS`.
- It explicitly has no subprocess, HTTP, GitHub mutation, filesystem-write, dispatch, or task-handler implementation.
- The current task catalog `.github/autonomous-loop-tasks.json` contains four narrowly scoped test-authoring instructions and allowed-path lists, but no executable handler contract. Do not interpret instruction text as executable task code.
- Therefore no real Worker Adapter can be enabled yet. Add a finite typed handler registry and deterministic input/output schema first; never accept shell commands, arbitrary URLs, import paths, or source code from queue payloads.

### Step 4 — free GitHub Actions budget evidence
- `scripts/orca_github_native_budget_evidence.py` is a verifier only; it has no collector.
- The current GitHub billing usage API documentation exposes user usage endpoints only for accounts with the enhanced billing platform, and organization usage endpoints require organization administrator access. Usage records report metered usage; they do not by themselves prove a universally available personal Free-plan included-minutes allowance or remaining free quota.
- Do not synthesize included minutes from usage records, and do not self-sign workflow evidence. Until a trusted, read-only source proves the applicable plan allowance and complete usage coverage, budget remains BLOCKED.

### Step 5 — Emergency Stop
- LINE and terminal entrypoints both call the same durable GitHub-state STOP latch. LINE checks the configured user allowlist; the app comments identify LINE SDK signature validation before the handler.
- Terminal entrypoint: `python -m scripts.orca_emergency_stop --reason "operator requested emergency stop"`.
- LINE commands: `緊急停止`, `緊急停止: 理由`, `ORCA STOP`, `EMERGENCY STOP`.
- These are code paths, not proof of operational availability. Both require valid state-store configuration and an existing state branch/document. The `orca-state` branch is not provisioned; STOP cannot yet be claimed operational. No ChatGPT STOP integration exists.

### Overall status
- 30-minute cron exists on the Draft PR branch only; it is not active on the default branch.
- `execution_enabled=false` remains mandatory. No worker execution, state-branch provisioning, secret/permission changes, merge, deployment, or schedule activation has occurred.
- Remaining acceptance gates: typed allowlisted worker and durable outcome/CAS integration; trusted budget collector/evidence; real independent review; operational shared STOP with state provisioned under separate authorization; then an explicitly approved non-production trial and separately approved cadence activation.
