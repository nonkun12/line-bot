# LINE AI Secretary

LINE Bot + MCP + AI Agent based assistant system.

## AI Debug Agent

### Phase 1 Completed

Implemented the foundation of AI-assisted debugging.

Features:

- Added `debug_agent` module
- Added debug workflow foundation
- Added collectors structure
- Added safety layer
- Prepared future AI-based error analysis

### Deploy Agent (Phase 4c) and Safe Automation Flags

The pipeline (`agents/patch/node.py`, `agents/commit/node.py`,
`agents/deploy/node.py`) is safe by default: every automatic file-changing,
committing, or deploying step is gated behind an explicit environment
variable that defaults to `false`. Nothing is applied, committed, or
deployed unless you opt in.

| Env var | Default | Behavior |
|---|---|---|
| `AUTO_APPLY_PATCH` | `false` | When `false` (default), `patch_apply_node` does nothing and passes Fix Agent's result through unchanged. When `true`, it validates the generated unified diff with `git apply --check`, then applies it on a new temporary branch (`fix/auto-<uuid>`) so the working branch is never touched directly. |
| `AUTO_DEPLOY` | `false` | When `false` (default), `deploy_node` only returns a "pending manual approval" result after a successful commit and never contacts Render. When `true`, it calls `render_client.trigger_deploy()` to actually start a Render deploy. |
| `RENDER_API_KEY` | (required only when `AUTO_DEPLOY=true`) | Render API key. If missing, `trigger_deploy()` returns an error result instead of raising an exception. |
| `REPO_WORKDIR` | current working directory | Repository path used by `patch_apply_node`, `test_runner_node`, and `commit_node` for git/pytest operations. |

`render_client.trigger_deploy()` calls
`POST https://api.render.com/v1/services/{SERVICE_ID}/deploys` and returns a
dict describing whether the deploy was triggered (`triggered`, `deploy_id`,
`status`, `error`). Failures are captured and returned, never raised.

Commit only happens if pytest passed (`agents/commit/node.py`), and deploy
only happens if commit succeeded (`agents/deploy/node.py`) — so the full
chain (`patch → pytest → commit → deploy`) fails safe at every step.

Covered by unit tests: `tests/test_deploy_node.py`, `tests/test_render_client.py`,
`tests/test_commit_node.py`, `tests/test_patch_node.py` (all mocked; no real
network calls or file writes in tests).

## Development Roadmap

### Phase 1
✅ AI Debug Agent foundation

### Phase 2
- Log collection
- Error classification
- AI root cause analysis
- Debug suggestions

### Phase 3
- Automatic fix generation
- GitHub Pull Request creation
- Self-improving development assistant


## Future Candidates

External projects that may improve AI Debug Agent.

### slopguard

Repository:
https://github.com/Blue-B/slopguard

Purpose:
AI generated code quality check

Possible Integration Point:
fix_agent → approval_agent

Notes:
- Candidate only
- No integration yet
- Evaluate after approval workflow is completed

