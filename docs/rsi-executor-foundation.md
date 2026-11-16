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

The test file is added but has not been executed in this change. A passing
GitHub Actions run, live local-model integration, trusted budget source, and
runtime control-plane wiring are not claimed. The next integration task is to
connect the control provider, local runner, and independent evaluator to
verified local adapters while preserving the default execution-off state.
