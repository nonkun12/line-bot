# Maintenance AI (bounded MVP)

## Purpose
Maintenance AI is a dedicated, read-only maintenance role for distributed-loop failures. It converts structured task evidence into a small, sanitized diagnostic report so the Control Tower can distinguish completed work, safety blocks, Recovery AI holds, and failures that still need log inspection.

## Operating contract
- Input: run-scoped `minimal-autonomous-loop.jsonl` only.
- Output: `maintenance-ai/diagnosis.json` artifact, scoped to the current run.
- No network calls, model/API spend, secret access, source edits, retries, hold clearing, branch publishing, merging, or deployment.
- Unknown and incomplete evidence fails closed and requires human review.
- Recovery AI remains the authority for retry/hold state. Maintenance AI cannot override it.
- A diagnosis is advisory. A repair proposal must be separately reviewed, tested, and approved by the Control Tower.

## Run #812 finding
The structured result says `status=FAIL`, `failure_reason=task_runtime_failed`; Recovery AI says `action=HOLD`, `requires_human=true`; Control Tower says `STOP / HOLD_FOR_REVIEW`. The job log further identifies a stale test expectation: the test expected the old `all_pending_tasks_held` reply, while current fail-closed behavior returns the explicit unavailable-artifact message. The multi-agent repair attempt was rejected with `invalid_change_count`; no patch was published.

## Next phase
Add a separately gated repair-proposal stage that consumes verified job-log excerpts, emits a patch proposal on an isolated branch, and cannot clear holds or merge. Do not enable that stage until this read-only triage is tested and the Control Tower contract is defined.
