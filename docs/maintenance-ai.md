# Maintenance AI (bounded MVP)

## Purpose
Maintenance AI is a dedicated, read-only maintenance role for distributed-loop outcomes. It converts structured task evidence into a small, sanitized diagnostic report so the Control Tower can distinguish completed work, safety blocks, Recovery AI holds, queue exhaustion, and failures that still need log inspection.

## Operating contract
- Input: run-scoped `minimal-autonomous-loop.jsonl` only.
- Output: `maintenance-ai/diagnosis.json` artifact, scoped to the current run.
- No network calls, model/API spend, secret access, source edits, retries, hold clearing, branch publishing, merging, or deployment.
- Unknown and incomplete evidence fails closed and requires human review.
- REA safety blocks and Recovery AI holds take precedence over contradictory PASS statuses.
- `NOT_RUN` / `queue_empty` is classified as `queue_exhausted`; `all_pending_tasks_held` is classified separately as `all_tasks_held`.
- Recovery AI remains the authority for retry/hold state. Maintenance AI cannot override it.
- A diagnosis is advisory. A repair proposal must be separately reviewed, tested, and approved by the Control Tower.

## Run #813 finding
The run completed successfully and uploaded the Maintenance AI diagnosis artifact. The task evidence contained `failure_reason=queue_empty`, but the first implementation classified it as `insufficient_evidence` and emitted `status=UNKNOWN`. This patch corrects that classification and adds regression tests. The run executed no task; workflow success only confirms the bounded workflow completed, not that development work was performed.

## Next phase
Use a real failed-task fixture and verified workflow-log evidence to validate runtime-failure diagnosis. Keep any repair-proposal stage separately gated; it must not clear holds, merge, or deploy.
