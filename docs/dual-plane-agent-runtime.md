# Dual-Plane Agent Runtime Architecture

Status: architecture contract plus IDEA recurring-plan prototype; end-to-end scheduler activation is not yet verified.
Repository: `nonkun12/line-bot`
Date: 2026-11-10

## Goal

Keep useful coordination and work moving while the Mac is offline, without pretending that Mac-local models or tools can execute remotely. The runtime is split into two independent planes with a durable hand-off boundary.

## Plane A — cloud-resident coordination and work

**Must continue without the Mac.** This plane owns task intake, classification, planning, durable state, cloud-safe specialist work, evidence collection, independent review, retry policy, and user-facing status.

Current repository foundations:
- `.github/workflows/distributed-autonomous-loop.yml`: bounded hosted loop, durable loop-state restore, kill switch, and fail-closed gates.
- `.github/workflows/distributed-loop-postrun.yml`: post-run evidence verification.
- `.github/workflows/continuous-distributed-loop.yml`: bounded continuation only after verified PASS and evidence.
- `.github/workflows/hourly-self-improvement-sidecar.yml`: hourly read-only history analysis.
- `core/management_ai.py`, `core/distributed_scheduler.py`, and `core/agent_communication.py`: bounded management, scheduling, and message contracts in the application code.
- `core/idea_ai.py` and `core/idea_execution_plan.py`: expanded ideation domains and a validated recurring-plan proposal contract. This is not yet a deployed recurring scheduler.

Important distinction: GitHub Actions being hosted does **not** mean a hosted LLM is available. The current distributed workflow explicitly disables the unverified Hermes advisor and Creator-Critic. Cloud AI inference must be marked unavailable until a real cloud-safe provider adapter and its credentials/runtime are verified. No Mac-local Ollama endpoint may be treated as cloud reachable.

### IDEA — exploration and recurring-work designer

IDEA is not merely a suggestion generator. It should:
1. Discover opportunities across product value, cross-agent collaboration, learning quality, new capabilities, reliability, and efficiency.
2. Preserve unconventional proposals and state the assumption, expected positive impact, and measurable success signal.
3. Turn accepted proposals into bounded plans: cadence, time window, timezone, task owners, dependencies, outputs, idempotency scope, and quality gates.
4. Route plans to Orca. Orca checks resource availability, conflicts, safety policy, and evidence requirements before scheduling.
5. Learn from PASS / NO_CHANGE / BLOCKED / FAILED results and propose improvements to the next cycle.

IDEA cannot activate workflows, grant permissions, approve its own proposals, clear HOLD, or authorize merge/deploy. Safe, reversible content-generation steps may be eligible for scheduled execution after Orca accepts the plan. Changes to approved learning data, user history, protected configuration, workflow activation, and external side effects retain their explicit approval gates.

### Example: daily core-English vocabulary improvement

The reference plan in `core/idea_execution_plan.py` proposes a daily morning cycle in `Asia/Tokyo`:
1. IDEA selects useful candidate headwords against the existing registry and history.
2. English Learning AI drafts core image, part of speech, natural example, accurate Japanese translation, and related words.
3. Independent reviewer / REA checks meaning, usage, naturalness, translation completeness, and duplicates.
4. Orca stages only PASS candidates with evidence and idempotency keys.
5. English Learning AI creates review practice and returns learner feedback to the next selection cycle.

The plan remains `PROPOSED`; it is not a live schedule. PASS candidates can be staged as review candidates, but the approved vocabulary registry, existing words, and learner history are not silently modified. The time window is “morning”, not an invented exact clock time.

Responsibilities:
1. Accept cloud-addressable requests (LINE/webhook/GitHub events) and persist a task envelope.
2. Assign only work whose required tools and data are available in the cloud.
3. Let cloud-resident agents exchange bounded messages through a durable coordinator.
4. Run REA-style read-only review against immutable evidence; a review result is not merge approval.
5. Keep retry counts, deadlines, ownership, dependencies, and state transitions durable.
6. Send Mac-bound work to Plane B's pending queue without blocking Plane A.
7. Report cloud work as PASS, NO_CHANGE, BLOCKED, FAILED, or WAITING_FOR_MAC with evidence.

## Plane B — Mac-local execution

**May be unavailable for hours or days.** This plane owns tasks requiring local filesystem access, GUI/Computer Use, local applications, local models, or private Mac resources.

Mac-local candidates:
- Hermes / Computer Use: GUI and local desktop operations.
- OpenClaw gateway and opencode-host: local agent runtime and ACP host.
- OpenCode: code editing/execution when running on the Mac host.
- Bonsai 9B and LFM3 1.7B: local model inference through their configured local runtimes.
- Obsidian/local vault operations: only while the Mac and vault are available.

Rules:
1. Plane B is never a prerequisite for Plane A health or progress.
2. When Mac is offline, tasks remain durable in `PENDING_MAC`; they are not silently dropped, marked complete, or repeatedly dispatched.
3. On reconnect, a single local worker claims eligible tasks atomically, verifies task identity and approval, then executes within its declared resource scope.
4. Interrupted work returns to a recoverable pending state; it never becomes PASS without verification.
5. The worker reports result, evidence references, changed resources, and remaining work to the cloud coordinator.
6. Local models are not advertised as cloud workers. If the local model is unavailable, tasks needing it remain queued or are explicitly reassigned to a verified cloud-capable worker.

## Shared hand-off contract

Every cross-plane task uses a versioned envelope with:
- `task_id`, `correlation_id`, `created_at`, `expires_at`;
- `execution_plane`: `cloud` or `mac`;
- `required_capabilities` and explicit resource scope;
- `status`: `QUEUED`, `CLAIMED`, `RUNNING`, `REVIEW_PENDING`, `PASS`, `NO_CHANGE`, `BLOCKED`, `FAILED`, `PENDING_MAC`;
- `approval_state` (separate from task status);
- bounded input, result summary, evidence references, attempt count, and idempotency key.

Messages are observations and results only. They never grant tool permissions, approve their own task, clear a HOLD, or authorize merge/deploy. All payloads are schema-validated; unknown agents, capabilities, statuses, and resource scopes fail closed.

## Communication topology

```text
IDEA -> recurring plan proposal -> Orca scheduling/safety gate
                                      |
                                      v
LINE / GitHub events -> cloud control plane (Orca / Management)
                         |
                         +----> cloud-safe specialists
                         |          |
                         |          v
                         |      REA read-only review
                         |          |
                         |          v
                         |      evidence + durable state
                         |
                         +----> PENDING_MAC queue
                                      |
                               Mac reconnects
                                      |
                                      v
                           Local worker / Hermes / OpenCode
                                      |
                                Bonsai / LFM3
                                      |
                               result + evidence
                                      |
                                      v
                           Cloud coordinator -> REA
```

## Availability and failure policy

| Condition | Cloud plane | Mac plane |
|---|---|---|
| Mac offline | Continues cloud-safe work | Queue only |
| Cloud workflow unavailable | Durable requests wait; no false completion | Local work may continue only if already authorized and safely isolated |
| Local model unavailable | Continues unrelated work | Model-dependent tasks wait or use an explicitly verified alternative |
| Missing evidence / REA HOLD | Stop affected task and preserve evidence | Do not claim PASS or auto-resume |
| Duplicate delivery | Idempotency key prevents duplicate execution | Atomic claim prevents two local workers taking one task |
| Reconnect | Reconcile queue and report status | Claim only eligible, unexpired, approved tasks |

## Existing code vs. new integration work

Already present as code foundations: bounded in-process agent messages, dependency-aware scheduler, management planner, hosted GitHub Actions workflows, durable loop-state branch, post-run verifier, hourly read-only self-improvement report, expanded IDEA proposal domains, and a validated recurring-plan contract.

Documented but not yet proven as an end-to-end deployed path: durable shared cloud-to-Mac queue, atomic Mac reconnect worker, cloud-to-local result reconciliation, recurring-plan scheduler/activation, and real inter-agent transport across separate processes/runtimes. These must be implemented and tested before describing the agents as densely connected or recurring plans as active.

## Delivery phases

1. **Contract and inventory** — keep the two planes separate; label every agent by runtime, capability, evidence, and availability.
2. **IDEA planning** — generate diverse opportunities and convert accepted ones into bounded recurring plans; keep plans PROPOSED until Orca validates them.
3. **Durable hand-off** — implement the versioned task envelope, idempotency, lease/claim, expiry, and `PENDING_MAC` state using existing repository persistence where safe.
4. **Cloud collaboration** — connect the management planner, durable coordinator, specialist mailboxes, and REA evidence review; no hosted LLM is assumed until verified.
5. **Recurring task execution** — start with non-destructive, reviewable content tasks such as vocabulary candidate generation; verify schedule, dedupe, quality gates, and durable state before enabling cadence.
6. **Mac reconnect adapter** — one local worker claims tasks, invokes only approved local adapters, and posts evidence/results.
7. **End-to-end verification** — simulate Mac offline, duplicate delivery, interrupted RUNNING, model unavailable, REA HOLD, and reconnect; prove cloud work continues and Mac work resumes once.

## Non-negotiable safety

- `AUTO_APPLY_PATCH=false`; `AUTO_DEPLOY=false`.
- No auto-merge, deployment, hold release, permission changes, or secret changes.
- Read-only audits remain read-only.
- All retries are bounded and evidence-backed.
- HOLD, missing evidence, expired approval, or unknown execution capability fails closed.
- This architecture document does not enable a workflow, dispatch a job, change a secret, or deploy a service.
