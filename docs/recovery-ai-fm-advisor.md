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
- The distributed-loop outcome adapter now supports opt-in attachment of advice through
  `RECOVERY_LOCAL_ADVISOR_ENABLED=true`. This is off by default and must only be enabled
  in a Mac-local environment where Apple's `fm` is available. Hosted GitHub Actions must
  leave it unset; no workflow secret or cloud model is required.
- Keep `AUTO_APPLY_PATCH=false` and `AUTO_DEPLOY=false`.

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


## Read-only diagnosis of an existing incident

Use `scripts/recovery_ai_mac_diagnostic.py` to inspect an incident already recorded
by the distributed loop. Unlike `recovery_ai_local_advisor`, this command does **not**
record a new failure or increment counters. It accepts either a standalone
RecoveryStore JSON file or the durable `.autonomous-loop-state.json` envelope and
extracts its `recovery_ai` section in memory only.

From a repository clone, first fetch the durable state branch without changing the
working tree or pushing anything:

```bash
git fetch --no-tags origin refs/heads/autonomous-loop-state:refs/remotes/origin/autonomous-loop-state
git show refs/remotes/origin/autonomous-loop-state:.autonomous-loop-state.json > /tmp/autonomous-loop-state.json
```

The exported file is a local diagnostic copy. Do not commit or upload it; it may contain
operational state. Then run the read-only diagnostic, replacing `example-task` with an
existing task ID:

```bash
python -m scripts.recovery_ai_mac_diagnostic \
  --state-file /tmp/autonomous-loop-state.json \
  --task-id example-task
```

The result reports the incident's `updated_at` value when available. Missing files,
invalid JSON, or unsupported schemas return `ERROR` with exit code 2. `SKIPPED` means
the incident is absent, held, not allowlisted, or outside the bounded advisory budget;
it does not mean the underlying task succeeded.

This diagnostic is not connected to LINE or the hosted distributed loop. It does not
apply suggestions, run commands, modify state, resume held tasks, patch, merge, or deploy.
Keep `AUTO_APPLY_PATCH=false` and `AUTO_DEPLOY=false`. The separate
`recovery_ai_local_advisor` CLI records a new failure, so never use it for a status check.
