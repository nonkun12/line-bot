# Local multi-agent peer review

## What is implemented

- `RequestScopedAgentFactory` creates one logical agent identity per planned task (maximum six).
- `ManagementAI` sends each task's identity to the existing specialist executor.
- When peer review is configured, a different task agent reviews each result; single-task plans receive a separate review-only logical identity with no execution task.
- `NEEDS_REVISION` creates a bounded, target-specific revision request in the collaboration snapshot. It is not accepted as success and does not automatically rerun a specialist executor.
- Review evidence is part of final acceptance. Missing, failed, spoofed, or adverse review evidence fails closed.
- `ManagementRun.collaboration_snapshot()` returns bounded JSON-safe team and review status for a dashboard or audit record.
- `OllamaLocalModelCall` calls an OpenAI-compatible Ollama endpoint over loopback only.

These are logical task identities. They do not by themselves start separate operating-system processes or grant separate tools.

## Explicit local setup

Run Ollama on the **same execution host** as the application and make sure the selected model is already available there. The default endpoint is `http://127.0.0.1:11434/v1`.

Example wiring:

```python
from core.management_ai import ManagementAI

manager = ManagementAI.with_local_peer_review(
    executors,
    model="YOUR_INSTALLED_LOCAL_MODEL",
    base_url="http://127.0.0.1:11434/v1",
    planner=your_existing_planner,
)
```

`YOUR_INSTALLED_LOCAL_MODEL` must be the exact model name served by Ollama. The adapter uses `/chat/completions`, sends a bounded prompt with `temperature=0`, disables streaming, and applies a request timeout and response-size limit.

## Safety behavior

- Only `http://localhost`, `http://127.0.0.1`, or `http://[::1]` endpoints are accepted.
- HTTPS, remote hosts, LAN addresses, credentials in URLs, query strings, and fragments are rejected.
- No API key, cloud provider, remote fallback, automatic model download, or subprocess is used.
- If Ollama is unavailable or returns invalid output, the review adapter fails and the management run is `BLOCKED`.
- A configured review stage can handle a single planned task by creating one separate review-only identity. It has no task assignment and cannot be a review target.
- `NEEDS_REVISION` and `BLOCKED` both prevent acceptance. Revision requests are returned as evidence for a later controlled correction; the system does not automatically rerun specialist executors because their side effects and idempotency are not assumed.
- The planner and specialist executors retain their existing provider/runtime configuration; this adapter changes only the peer-review call. It does not claim the entire application is local-only.
- Do not point this adapter at a service running on a different host. In a hosted container, loopback refers to that container, not a developer laptop.

## Current rollout boundary

PR #1373 is still a Draft. The adapter is opt-in and is not automatically enabled by the application. No production deployment, workflow dispatch, merge, or substream restart is performed by this change.

Before enabling it in a runtime, install and verify the local inference server on that same host, then run the full CI and an approved integration trial. If the host cannot run a local model within the free resource budget, keep peer review disabled rather than switching to a paid or remote provider.


## Runtime wiring and dashboard audit

Local peer review remains disabled unless the application environment explicitly sets:

- `ORCHESTRATOR_LOCAL_PEER_REVIEW_ENABLED=true`
- `ORCHESTRATOR_LOCAL_PEER_REVIEW_MODEL=<installed Ollama model name>`
- Optional: `ORCHESTRATOR_LOCAL_PEER_REVIEW_URL=http://127.0.0.1:11434/v1`

When enabled without a model name, the multi-specialist request fails closed before specialist execution. The URL is still validated by the loopback-only adapter; remote hosts and cloud fallback are rejected. Do not enable this on a hosted runtime unless Ollama is installed and running inside that same runtime.

Each completed orchestration attempt writes only a bounded collaboration summary (agent IDs, roles, task IDs, peer-review state, and bounded findings) to the application SQLite database. The per-user history is capped at 20 records. The dashboard exposes it through the authenticated, read-only endpoint:

`GET /api/dashboard/orchestrator/collaboration?limit=10`

This endpoint reports evidence only. It cannot approve tasks, grant permissions, dispatch work, or change the execution queue. The authenticated dashboard page renders a read-only collaboration panel with the latest agent roster, task assignments, peer-review status, acceptance result, and bounded findings. It refreshes on demand and every 60 seconds. The panel cannot dispatch or approve work.
