# Autonomous Sprint Development Concept

## Purpose

Use short, evidence-driven development cycles to move a user-approved Goal toward a usable result. A sprint is a bounded unit of progress, not an open-ended autonomous loop. The Control Tower remains the top-level authority; specialist agents propose and execute scoped work under the Goal's server-side autonomy grant.

## Operating model

1. **Goal intake** — The Control Tower records the desired outcome, user-visible value, constraints, and measurable success criteria.
2. **Idea and discovery** — An Idea Agent generates multiple candidate approaches, checks originality and user value, and records assumptions. A separate Critic Agent challenges weak assumptions. The Control Tower selects or asks for clarification when the choice materially changes the Goal.
3. **Sprint planning** — Convert the next smallest valuable increment into a sprint with:
   - a single sprint goal;
   - a small, ordered set of child JOBs and dependencies;
   - explicit deliverables and acceptance criteria;
   - a bounded job/attempt budget and allowed paths/stages;
   - risks, rollback/recovery approach, and required evidence.
4. **Execution** — The existing Goal JOB chain schedules one durable child JOB at a time. Work is resumable and idempotent. No worker may expand its own permissions or bypass the grant.
5. **Verification** — Run focused tests, relevant regression tests, static checks, and independent evidence evaluation. A worker's self-reported success is not sufficient.
6. **Sprint review** — Compare delivered evidence with acceptance criteria. Record completed, incomplete, failed, and blocked work separately.
7. **Retrospective and next sprint** — Capture root causes, recurring failures, and process improvements as backlog items. Generate the next bounded sprint only when the prior result is reconciled. Continue until the Goal is achieved or a genuine HOLD condition requires human input.

## Sprint state contract

A sprint should be represented as a durable, auditable record linked to one Goal:

- `sprint_id`, `goal_id`, sequence number, status, created/updated timestamps;
- sprint goal, selected JOB keys, dependencies, budget, and scoped permission snapshot;
- acceptance criteria and evidence references;
- review result, unresolved blockers, and retrospective actions.

Suggested lifecycle: `planned -> active -> review -> completed`. A sprint may instead end as `blocked` or `cancelled`. Do not silently mark incomplete work as completed. Retrying a failed sprint must create an auditable retry/repair decision rather than erase history.

## Definition of Ready

A sprint is ready only when its goal is clear, the work is decomposed, dependencies are known, acceptance criteria are testable, the permission scope is valid, the budget is bounded, and required inputs are available. If not, return a typed HOLD reason instead of generating empty or speculative work.

## Definition of Done

A sprint is done only when:
- its planned deliverables exist;
- every required acceptance criterion has independently verified evidence;
- focused and relevant regression tests pass;
- no unresolved critical/high-risk finding remains;
- changes stay within the approved path and cost constraints;
- review and retrospective records are persisted;
- the next backlog item or Goal completion decision is explicit.

## Safety and cost invariants

- Free-only is mandatory: no paid APIs, metered APIs, paid cloud, paid models, or expiring free-tier dependency as a required runtime path.
- Prefer existing hardware and free/open-source tools; check licenses and commercial-use terms for models, code, assets, and media.
- A sprint cannot authorize itself, widen its grant, bypass HOLD, merge, deploy, delete data, or perform external irreversible actions.
- Merge and deployment remain separate protected workflows.
- Stop safely on missing evidence, exhausted budget, permission mismatch, repeated failure, or ambiguous high-impact decisions.

## Game and audiovisual production

For game creation, the Idea Agent is an early sprint participant, not an afterthought. Candidate concepts should be scored on player experience, originality, clarity of the core loop, replay motivation, accessibility, production feasibility, and free-only feasibility. The selected concept becomes a testable prototype Goal.

A typical sequence is:
1. idea exploration and concept critique;
2. core loop, rules, story, and player journey;
3. smallest playable prototype;
4. playtest and evidence-based revision;
5. art, animation, sound, and original music integration;
6. accessibility, performance, regression, and release-readiness review.

For audiovisual work, lock the scenario and emotional arc before detailed production. Music and visual timing should be reviewed together, not as independent deliverables.

## Incremental implementation plan

1. Add sprint schema and store as an additive layer over the existing Goal tables.
2. Add deterministic planner functions for readiness, sprint selection, and budget enforcement.
3. Add review/retrospective persistence and a resumable sprint orchestrator.
4. Add tests for idempotency, interruption recovery, exhausted budgets, missing evidence, permission boundaries, and HOLD behavior.
5. Connect the Control Tower and LINE intake only after the standalone contract and tests are stable.

Do not duplicate the existing Goal planner or worker. Reuse the current Goal JOB chain and add sprint-level planning, review, and learning around it.
