# Recovery AI core (phase 1)

## Safety boundary

`scripts/recovery_ai.py` is a deterministic recovery controller, not an autonomous
patching agent. It does not invoke an LLM, run commands, change source code, merge,
or deploy. It returns a decision that a separately guarded loop can consume.

- Transient infrastructure failures: at most two retry decisions, with bounded backoff.
- Repairable deterministic failures: at most one repair decision per identical
  task/category/failing-test fingerprint.
- Three consecutive failures, non-repairable/security failures, or exhausted repair
  budget: hold the task for explicit review.
- Only verified checkpoints may be persisted as resumable.
- Held tasks require explicit `cause_fixed=True` confirmation before resuming.
- Invalid/corrupt state and persistence errors are fail-closed.
- Failure fingerprints contain task ID, category, and sanitized test identifiers;
  raw logs, prompts, credentials, and exception text are not stored.

## Initial integration contract

The loop integration must call the controller only after capturing a structured,
sanitized result. It must persist the recovery decision before reporting it, stop
when persistence cannot be trusted, skip held tasks while allowing independent
healthy tasks to proceed, and retain `AUTO_APPLY_PATCH=false` and
`AUTO_DEPLOY=false`.

This phase deliberately does not change the existing distributed workflow or
claim production recovery. Before integration/activation, run the focused tests,
the complete repository test suite, and controlled fault-injection tests. Then
verify a bounded run, durable ledger read-back, and LINE report. Measure elapsed
time from failure detection to verified loop resumption; do not count a mere
retry request as successful recovery.
