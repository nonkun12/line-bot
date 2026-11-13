# Orca recursive self-improvement (proposal-only core)

## Purpose

Run a bounded evidence-driven improvement cycle under the existing Orca
Control Tower and existing Kanban. This is not an autonomous code-mutating
agent. The module records observations, diagnosis/proposal/test/review evidence,
and evaluation decisions. It does not write source files or authorize execution.

## Cycle

1. Observe a regression or measurable opportunity and attach immutable source references.
2. Diagnose a likely cause and attach evidence.
3. Propose one bounded change with expected metric and rollback criteria.
4. Test in isolation; attach test run and artifact references.
5. Obtain an independent Critic verdict and attach its review evidence.
6. Evaluate against a baseline. A positive result becomes
   `accepted_candidate`, meaning human review only. No improvement becomes
   `deferred`; failed checks are blocked.
7. Start the next cycle with a parent cycle ID. Recursion is capped at depth 10.

## Safety boundaries

- No source mutation, patch application, branch creation, PR creation, merge,
  deployment, credential changes, or Global HOLD release.
- `execution_authorized`, `auto_apply`, `auto_merge`, and `auto_deploy`
  remain false in every cycle.
- Missing evidence, non-sequential transitions, failed tests, or a non-PASS
  independent Critic verdict blocks evaluation.
- A metric improvement is not sufficient by itself to authorize production.
- Store cycle references in the existing Orca Kanban fields; do not create a
  separate Kanban.
- This is a pure state-machine contract. It is not wired to a scheduler,
  worker, durable store, or live metrics collector.

## Remaining integration

Connect Observe to trusted LOOP telemetry; route candidates to the existing
Orca improvement board; run tests in isolated worktrees; attach independent
Critic evidence; and require human approval before any protected change.


## Priority in the 30-minute Distributed AI LOOP

Recursive self-improvement is the primary workload and the LOOP scheduler is
only its cadence/transport layer.

### Phase 1 — observe and learn (read-only)

Every 30 minutes, collect only evidence that can be read safely:
- latest workflow/check conclusions and failure categories;
- queue counts, Global HOLD, lease consistency, and immutable state ref SHA;
- prior cycle stage, parent link, unresolved diagnosis, candidate and evaluation;
- whether the previous proposed improvement actually changed a measurable
  baseline, using source-linked test/CI artifacts.

The observer must not claim tasks or write state. Until a durable state ref and
a trusted metrics/evidence source exist, report the missing inputs explicitly;
never fabricate a baseline or score. Each observation can produce a
proposal-only cycle record only after its evidence references are available.

### Phase 2 — one bounded improvement per cycle

After Phase 1 is accepted and separately authorized, process at most one
improvement candidate per 30-minute run. Prefer in this order:
1. fix a reproducible test/CI regression;
2. remove a verified safety or reliability weakness;
3. reduce recurring failure/latency/resource use with a measurable baseline;
4. improve queue/worker throughput only after safety gates pass.

Each candidate must define: problem evidence, root-cause hypothesis, minimal
diff, expected metric, test plan, rollback condition, and independent Critic.
Run isolated tests; preserve a before/after baseline; carry the outcome and
unresolved issue into the next cycle using `parent_cycle_id`.

A candidate is not automatically applied. Human approval remains required for
patch application, PR creation, merge, deployment, Global HOLD changes, or any
credential/permission change.

### Anti-loop / quality controls

- Do not repeat an unchanged proposal without new evidence.
- If the same failure recurs twice, stop proposing superficial retries and
  escalate to root-cause analysis.
- If the metric is unavailable, stale, incomparable, or has no baseline,
  classify the cycle as `deferred`, not improved.
- Track both quality and cost/safety guardrails; an improvement that increases
  failure rate, consumes unverified quota, or weakens HOLD is rejected.
- Bound recursion depth and require independent evidence at every transition.

