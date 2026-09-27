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

Periodically review the whole AI topology, permissions, dependencies, queues, failure history, monitoring coverage, rollback capability, and safety-control integrity.

Loss of reliable system-wide visibility is itself a risk condition.

## Human and ChatGPT role

The long-term target is minimal intervention, not forced zero intervention. Human intervention and ChatGPT remain emergency/review paths while the autonomous system gains independent safety and recovery capabilities.

## Non-negotiable rule

When safety evidence is incomplete, contradictory, or unavailable, stop mutation and preserve the last verified state.
