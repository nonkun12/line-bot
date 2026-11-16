# GitHub-native RSI runtime — bounded first execution

This workflow is the first PC-independent execution slice of the five-stage
RSI cycle. It runs every 30 minutes on GitHub Actions and stores a cycle
artifact for 30 days.

## Five stages

1. Evaluate — run a fixed baseline matrix of repository-owned unittest files.
2. Diagnose — classify failures by fixed suite identity; do not assert an
   unverified root cause.
3. Hypothesize — create bounded, explicitly unverified investigation
   hypotheses.
4. Experiment — rerun each failed non-timeout suite once in a clean Python
   process.
5. Select & Evolve — PASS only when the baseline is clean; otherwise stop
   for human review. The next scheduled run starts a new evidence cycle.

## Execution boundary

- Only six hard-coded unittest files are executable targets.
- No queue text is interpreted as a command.
- No LLM, local model, paid API, secret, network client, source patch, branch,
  PR, merge, deployment, or Global HOLD change is used.
- Test processes receive a minimal environment and have a fixed timeout.
- Reports contain suite identifiers and statuses, not raw test output.
- A failing or timed-out suite fails the workflow and requires human review.

## Explicit limitation

This is scheduled test execution and a five-stage evidence cycle, not
autonomous code authoring. It does not generate patches or claim production
tasks. The existing approval, budget-evidence, durable-state, and worker
runtime gates remain separate prerequisites for any future code-changing
worker. No schedule in this workflow overrides those gates.
