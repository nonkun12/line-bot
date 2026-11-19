# Autonomous System Risk-Hedging Framework

Status: design baseline

## Objectives

The autonomous development system must remain safe when an individual AI fails, exhausts a free quota, behaves unexpectedly, or when the system itself requires major repair.

Safety has priority over throughput. Paid AI/API services are not a prerequisite.

## Safety states

- NORMAL: bounded autonomous development is allowed.
- DEGRADED: an AI/provider is unavailable; bounded fallback or non-AI recovery is allowed.
- ISOLATED: one AI/component shows anomalous behavior; its permissions and work queue are contained.
- REPAIR: structural repair is required; new feature work is suppressed.
- FULL_STOP: autonomous mutation is stopped. Investigation and read-only verification may continue.

Unknown or conflicting safety state must resolve to the safer state.

## Continuous loop availability

Outside REPAIR/FULL_STOP, the system should maintain at least one healthy autonomous loop.

- The whole-system loop is not the only execution path.
- Independent component loops may continue when another loop is failed or isolated.
- A failed loop must not imply system-wide shutdown.
- Watchdogs must detect unintended zero-loop states and attempt bounded recovery.
- Recovery must never bypass Safety Gate, verification, permission boundaries, or rollback requirements.
- FULL_STOP may stop mutation loops, but read-only monitoring/recovery-verification loops remain allowed.

This prevents a single component failure from turning into system-wide inactivity while preserving a hard stop for major repair.

## Backup and recovery architecture

Backup is a first-class safety control, not an afterthought.

### 1. Multiple recovery points

Before autonomous mutation, preserve the last verified recovery point:

- known-good Git commit/SHA
- relevant workflow/run identifiers
- test and Safety Gate evidence
- configuration/version metadata needed for recovery
- audit/ledger references
- active loop/safety state

Do not treat an unverified working tree or an AI-generated report as a recovery point.

### 2. Layered backup

Maintain independent layers where technically available:

- repository history as the primary code rollback source
- immutable or append-only audit records for execution evidence
- periodic workflow artifacts for diagnostics and recovery evidence
- configuration/state snapshots that exclude secrets
- external recovery records for critical state where available

A backup must be independently readable before it is considered usable.

### 3. Pre-change checkpoint

Every autonomous mutation cycle must establish:

1. base SHA
2. clean/expected working state
3. selected target scope
4. current Safety Gate state
5. test/verification baseline
6. rollback reference

If the checkpoint cannot be established, mutation is blocked.

### 4. Rollback

Rollback must be bounded and evidence-driven.

- Restore only to a verified recovery point.
- Verify the actual resulting SHA/state after rollback.
- Re-run the required safety and regression checks.
- Record the rollback reason and result.
- Never let the failing AI authorize its own rollback exception.

### 5. Backup verification

Backup success means more than "backup command succeeded".

Periodically verify:

- the recovery point exists
- it can be read
- its SHA/state is internally consistent
- required metadata is present
- restoration procedures remain compatible
- the verification itself is logged

A failed backup verification is a safety signal and must not be silently ignored.

### 6. Recovery drills

Run bounded, non-destructive recovery checks periodically. Test that:

- a failed individual loop can be isolated
- a loop can restart from a verified checkpoint
- a bad change can be identified and rolled back
- monitoring survives component failure
- FULL_STOP remains effective
- recovery does not expand permissions

Do not perform destructive restore drills against production state automatically.

### 7. Backup independence

No single AI, loop, provider, or credential should be the sole path to recovery.

In particular:

- the component being repaired must not be the sole backup verifier
- the same provider should not be the only recovery dependency when alternatives exist
- backup metadata must not depend exclusively on the mutable system it protects
- secrets must not be copied into general backup artifacts

### 8. Recovery hierarchy

Use the smallest safe recovery action first:

1. restart/requeue isolated loop
2. restore its last verified local checkpoint
3. rollback the affected component
4. isolate dependent components
5. enter REPAIR
6. enter FULL_STOP when safety boundaries or system-wide visibility are compromised

### 9. Backup failure policy

If the system cannot establish a reliable recovery point for a mutation:

**do not mutate.**

If an existing backup becomes unreadable, inconsistent, or unverifiable:

**preserve the last independently verified state and escalate the safety state.**

## Multi-angle monitoring

Monitor independently:

1. execution health: timeout, crash, hung loop, retry count
2. artifact integrity: base SHA, produced SHA, diff, changed-file scope
3. test/verification evidence: tests and independent verification
4. permissions: tool access, secret access, transitive authority
5. AI behavior: unusual tool calls, fallback storms, repeated failures
6. dependency/provider health: quota, auth, API failure, model availability
7. audit integrity: self-improvement history and Google Sheets ledger
8. infrastructure health: CI, runtime, external services
9. monitor health: watchdog and verification paths themselves
10. backup/recovery health: checkpoint availability, readability, integrity, restore readiness

A monitoring report is not evidence by itself; it must be checked against observable system state.

## Mutual AI checking

No AI should be the sole approver of its own work.

Implementation, testing, verification, security review, and admission of a new AI must be separated. Conflicting assessments must not be resolved by optimistic majority vote; the safe outcome is to block and re-check.

## Blast-radius containment

Each AI must have bounded authority. A single AI failure must not automatically grant access to another AI's tools, secrets, or queues.

Anomalous behavior should trigger:

1. isolate the AI
2. stop its queue/work
3. revoke or suspend its effective authority where safely possible
4. preserve evidence
5. independent verification
6. restore only after explicit recovery checks

If the anomaly crosses component boundaries or affects monitoring/safety controls, escalate to FULL_STOP.

## New AI admission

A newly generated AI is never fully trusted merely because it passed a functional test.

Before formal integration, verify:

- purpose and role
- code and dependencies
- minimal permissions
- tool/data access
- external communication
- AI-to-AI authority chains
- fallback behavior and bounded retries
- kill-switch behavior
- regression tests
- independent verification
- security review
- rollback path
- telemetry/auditability

The new AI cannot approve its own admission.

## Major repair

Repeated failures, broad dependency impact, safety-control changes, monitoring disagreement, or loss of system-wide visibility can trigger REPAIR or FULL_STOP.

During FULL_STOP:

- no autonomous feature development
- no automatic deployment
- no permission expansion
- no Safety Gate weakening
- no automatic admission of new AI
- investigation, evidence preservation, tests, and verification remain allowed

Return to NORMAL only after recovery checks pass.

## Provider/quota failure

AI exhaustion or provider failure must not equal system failure.

Use bounded fallback. If all allowed providers are unavailable, record the condition and enter a safe waiting state. Do not introduce paid providers automatically.

## Periodic system-wide review

Periodically review the whole AI topology, permissions, dependencies, queues, failure history, monitoring coverage, rollback capability, backup health, and safety-control integrity.

Loss of reliable system-wide visibility is itself a risk condition.

## Human and ChatGPT role

The long-term target is minimal intervention, not forced zero intervention. Human intervention and ChatGPT remain emergency/review paths while the autonomous system gains independent safety and recovery capabilities.

## Non-negotiable rule

When safety evidence is incomplete, contradictory, or unavailable, stop mutation and preserve the last verified state.
