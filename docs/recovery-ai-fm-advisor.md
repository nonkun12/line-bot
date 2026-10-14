# Recovery AI: local Apple Foundation Model advisor

This is an **optional Mac-only diagnostic helper** for Recovery AI. It calls Apple's
`fm respond` CLI for on-device diagnostic suggestions.

## Safe integration boundary

- `scripts/recovery_ai.py` remains the authoritative deterministic controller.
- `record_failure_and_advise()` records one newly observed incident through
  `RecoveryStore.record_failure()`, then passes that actual returned decision to the
  advisor bridge. The caller cannot supply or override the decision action.
- The local advisor asks fm only when the recorded decision is `REPAIR_ONCE` and the
  category is allowlisted (`test_regression`, `timeout`, or `process_crash`).
- `HOLD`, `STOP_FAIL_CLOSED`, `RETRY`, security violations, invalid evidence, and
  other categories skip diagnosis.
- The result is marked `ADVISORY_ONLY`; it is not a repair instruction. The advisor
  does not execute commands, edit files, apply patches, merge, or deploy.
- State persistence errors stop the flow before the local advisor is called. Adapter
  failures or invalid output produce `UNAVAILABLE`; the deterministic decision remains
  authoritative.
- The CLI records a failure and increments its counter. Invoke it **once per newly
  observed incident**, not as a status check or retry; duplicate invocation can exhaust
  the bounded repair budget and cause a hold.
- Never pass raw logs, prompts, tracebacks, or secrets; provide identifiers only.
- The hosted distributed loop must not invoke this Mac-only adapter. Keep
  `AUTO_APPLY_PATCH=false` and `AUTO_DEPLOY=false`.

## Opt-in use on a Mac

```bash
python -m scripts.recovery_ai_local_advisor \
  --state-file "$HOME/.local/state/line-bot/recovery-state.json" \
  --task-id example-task \
  --category test_regression \
  --failing-test tests/test_example.py
```

The CLI obtains the decision from the deterministic controller; do not run it merely to
inspect an existing incident because each invocation records a new failure. It is not
connected to the hosted loop and requires a real newly observed incident on a Mac.
Advice must be independently reviewed before any repair work.
