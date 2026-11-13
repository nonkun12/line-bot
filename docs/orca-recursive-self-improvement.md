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
