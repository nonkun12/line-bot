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

## Local Mac media worker

Video and audiovisual rendering should use the user's existing Apple Silicon Mac as an optional local execution worker. Keep Goal orchestration, sprint state, permissions, and durable JOB records in the existing control plane; do not move orchestration authority onto the Mac.

### Responsibility split

- **Control plane**: accepts the Goal, plans the sprint, issues a narrowly scoped media JOB, tracks status, verifies returned evidence, and decides the next step.
- **Mac media worker**: claims only explicitly authorized media JOBs, performs local asset preparation, compositing, audio mixing, encoding, preview generation, and local quality checks, then returns artifact metadata and verification evidence.
- **Specialist agents**: produce the scenario, storyboard, shot list, visual direction, music brief, and timing map before rendering. The video worker must not invent or silently rewrite the approved scenario.

### Mac worker safety contract

- The worker is opt-in and on-demand; do not require a permanently running server or launch-at-login process.
- Use a local authenticated bridge with expiring, single-purpose job grants. Validate job ID, allowed operation, input manifest, output directory, resource budget, and deadline before execution.
- Restrict writes to a dedicated project workspace. Never expose arbitrary shell execution, general filesystem access, secrets, or unrelated personal files to a remote job.
- The Mac may pull a queued job and report progress, but the control plane cannot issue unrestricted commands to the Mac.
- Provide pause/cancel, graceful shutdown, disk-space checks, thermal/power-aware limits, and resumable checkpoints. Clean up only temporary files owned by that job.
- Keep source media and rendered artifacts on the Mac by default. Return only status, hashes, dimensions, durations, test results, and user-approved preview references unless the user explicitly requests transfer.
- Do not automatically publish, upload, merge, or deploy rendered content.

### Free local media pipeline

Prefer installed system capabilities and free/open-source tools, subject to local availability and license checks. Start with deterministic editing and rendering (timeline, transitions, titles, compositing, audio mixing, encoding) rather than requiring a paid generative-video service or a large local video model. Use Apple hardware acceleration only when the selected local tool exposes it and a capability check confirms it works. A model running locally for language/planning is not itself a video-generation engine.

A practical first increment is a local render worker that can:
1. validate a scenario/storyboard and asset manifest;
2. assemble a short animatic from stills, text, timing, and audio cues;
3. mix a locally generated or user-provided soundtrack with scene timing;
4. render a preview and run duration/audio/video integrity checks;
5. return evidence and a local artifact reference to the sprint review.

Only after this reliable baseline passes should later sprints add more advanced animation or local generative models, gated by actual Mac memory, storage, thermals, speed, and license checks.

### Incremental rollout

1. Read-only capability discovery: OS/architecture, memory, free disk, installed media tools, hardware-encoding support, and worker reachability. Do not install or start persistent services.
2. Local-only prototype: render a tiny test project manually/on-demand and record resource usage.
3. Sandboxed worker: add job manifest validation, workspace isolation, bounded execution, cancellation, and evidence reporting.
4. Control-plane integration: connect the worker through a narrow pull-based bridge and test disconnect/retry/idempotency.
5. Sprint integration: let the Control Tower route only media/render jobs to the Mac; all planning, approval boundaries, and Goal completion remain centralized.

The known environment includes Apple Silicon (arm64) on macOS 27.2 and an existing on-demand Bonsai MLX setup. Bonsai can assist local language tasks, but its presence does not establish that a video model or renderer is installed. Exact memory/GPU capacity and media-tool availability must be discovered before selecting workloads.

