# Stage 132: loopback local-model adapters

Stage 132 adds a concrete Ollama-compatible HTTP client and connects local
model output to the AI Factory proposal path without granting the model tools.

## Local endpoint contract

- Only plain HTTP loopback URLs are accepted: `127.0.0.1`, `localhost`,
  or `::1`; the default Ollama port is 11434.
- Proxy environment settings are ignored for this client.
- Calls use non-streaming `/api/chat`, bounded prompts/responses, a bounded
  timeout, and a bounded output-token count.
- No credentials, remote endpoints, tool calls, shell execution, file writes,
  or automatic retries are supported.

## Role separation

- DESIGN and BUILD may receive local-model proposal text through separate, independently injected client instances.
- TEST and REVIEW must be supplied by separate independent gate producers.
  Local-model text is never allowed to set `passed=True` or `approved=True`.
- Missing independent gates fail closed.
- The model-generated AgentSpec is strict-schema JSON, GENERATED lifecycle,
  with empty tool and resource scopes and fixed least-privilege constraints.
- Model-generated validation test names are proposals; the Stage 121 sandbox
  must execute real tests and the independent reviewer must approve separately.

## Runtime limitation

This adapter calls a loopback Ollama-compatible server on the machine running
the Python process. GitHub-hosted CI cannot reach a user's private/local model.
CI uses fake clients for deterministic tests. Real model smoke tests require
an explicitly operated local runner with the Ollama service already available;
no Mac setup, cloud fallback, or paid API is introduced here.

## Non-goals

No scheduler, persistent catalog, approval source, permissions, activation,
merge, deployment, or production workflow is changed.
