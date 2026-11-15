# Local multi-agent peer review

## What is implemented

- `RequestScopedAgentFactory` creates one logical agent identity per planned task (maximum six).
- `ManagementAI` sends each task's identity to the existing specialist executor.
- When peer review is configured, a different task agent reviews each result.
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
- A configured review stage requires at least two planned task agents. A single-task request cannot independently review itself and is `BLOCKED`.
- The planner and specialist executors retain their existing provider/runtime configuration; this adapter changes only the peer-review call. It does not claim the entire application is local-only.
- Do not point this adapter at a service running on a different host. In a hosted container, loopback refers to that container, not a developer laptop.

## Current rollout boundary

PR #1373 is still a Draft. The adapter is opt-in and is not automatically enabled by the application. No production deployment, workflow dispatch, merge, or substream restart is performed by this change.

Before enabling it in a runtime, install and verify the local inference server on that same host, then run the full CI and an approved integration trial. If the host cannot run a local model within the free resource budget, keep peer review disabled rather than switching to a paid or remote provider.
