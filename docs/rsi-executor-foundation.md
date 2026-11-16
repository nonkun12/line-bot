# RSI Executor foundation (Stages 1-6)

This is a separate RSI experiment path. It is not the generic distributed-loop
worker and does not treat ordinary queue completion as self-improvement.

## Implemented foundation

1. **Typed RSI executor** — `core/rsi_executor.py` defines typed observations,
   diagnoses, hypotheses, experiment plans, approvals, results, and evaluations.
2. **Persistent evidence** — `EvidenceLedger` stores append-only SQLite records
   with a SHA-256 hash chain and update/delete-denying triggers.
3. **Diagnosis and hypotheses** — deterministic bounded diagnosis groups
   evidence-backed FAIL/REGRESSED observations. It labels causes unverified;
   it does not claim an LLM has discovered root cause.
4. **Independent evaluation** — the evaluator identity must differ from the
   executor, and a caller-supplied signature verifier must accept the report.
5. **Next-experiment selection** — deterministic, bounded selection ranks
   proposals by information value, cost, and risk.
6. **Safety tests** — tests cover HOLD, FREE-only, unknown budget, disabled
   execution, approval binding, evaluator separation, digest validation,
   duplicate evidence, and append-only ledger behavior.

## Local-model advisory integration

`core/rsi_local_advisor.py` reuses Stage 132's `LocalModelClient` and provides
`build_loopback_rsi_advisor()` pinned to `http://127.0.0.1:11434` with bounded
output. It supplies one alternative hypothesis and falsification test as
append-only proposal evidence. The model output is strict-schema validated and
cannot authorize execution, certify evaluation, grant approval, or activate a
model. This is advisory support; deterministic executor decisions remain the
source of the experiment plan and selection.

The existing Stage 160 gate governs the separate Stage 159 evolutionary merge
proposal contract. It is not silently treated as an adapter for generic RSI
plans: those types and authority scopes differ and require an explicit reviewed
bridge before any evolutionary merge experiment can be dispatched.

## Authority boundary

- Global HOLD, non-FREE paths, paid fallback, unknown budget, and insufficient
  budget fail closed.
- Planning is proposal-only. Execution additionally requires
  `execution_enabled=true`, a verified approval bound to the exact plan digest,
  and an injected local runner.
- The runner is an adapter; this module does not start a model or subprocess.
- An independent evaluator adapter and signature verifier are mandatory.
- No weight/tensor mutation, model merge, generation advancement, registry
  activation, production switch, auto-merge, or deployment is implemented.
- No scheduler or background worker is enabled by this change.

## Validation status

GitHub Actions validation for commit `58b6c14` completed successfully:
Python syntax scan, the full Pytest workflow, and the repository's free
deterministic-loop workflow all reported success. The deterministic-loop
workflow had an empty task queue and executed no RSI task. The AI Code Review
workflow also completed, but that workflow only checks out the repository and
prints the diff; it is not a substantive independent code review.

Live Ollama execution, a trusted budget source, a concrete experiment runner,
a signed independent-evaluator adapter, and runtime control-plane wiring are
not claimed. The generic RSI executor remains execution-off by default. The
next integration task is to provide verified local experiment/evaluation
adapters and a trusted read-only control/budget provider, then run them only in
an isolated local environment after explicit approval.


## End-to-end proposal cycle

`core/rsi_cycle.py` now orchestrates one bounded proposal cycle:
observation -> deterministic diagnosis -> falsifiable hypothesis -> optional
loopback local-model advisory note -> digest-bound plan -> deterministic
selection. It returns an explicit `PROPOSAL_READY` or
`NO_IMPROVEMENT_TARGET` state. It never invokes a runner, grants approval,
certifies evaluation, or activates a model. Advisor failure stops the cycle
rather than being interpreted as a pass.

Planning now checks the known remaining FREE budget against the requested
experiment cost before creating plans; selection excludes plans that are no
longer affordable. The budget value is still supplied by an injected provider,
not claimed to be a trusted live account-wide quota measurement.
