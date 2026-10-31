# Hermes local worker queue via private GitHub Issues

## Decision

Use GitHub Issues in the private nonkun12/ai-dispatch-queue repository as the durable hand-off between the existing Render LINE webhook and the Mac-local Hermes worker.

Do not deploy the current in-memory HTTP queue prototype from PR #1. Its process-local list is lost on restart, it has no authentication, and it does not provide a safe claim/lease protocol.

## Data flow

1. Keep LINE Developers Console pointed at the existing Render endpoint: https://line-bot-yvea.onrender.com/callback.
2. Render validates the LINE event and the existing development-user allowlist.
3. Render creates one issue in the private queue repository. The issue contains a request ID, bounded instruction, requesting LINE user ID, creation time, and an explicit approval state. Do not include channel secrets, access tokens, or unrelated chat history.
4. A single Mac-local Hermes worker polls the private repository outbound using an authenticated GitHub CLI/API session. No inbound tunnel to the Mac is needed.
5. The worker claims a pending issue by changing its queue label, then runs only tasks whose approval state permits execution.
6. The worker posts a structured result (status, task ID, commit SHA, changed files, test evidence, and error summary) and closes only successfully completed queue items. Failed or interrupted tasks remain visible for recovery.
7. Render sends the concise result to the original LINE user through the existing /internal/push quota guard.

## Queue states

- queue:pending: accepted and waiting for the local worker.
- queue:claimed: held by the single configured Mac worker.
- queue:running: execution started.
- queue:completed: completed with exact-SHA verification evidence.
- queue:blocked: approval, authorization, or safety gate prevented execution.
- queue:failed: execution failed; preserve logs and retry metadata.

The first release is intentionally single-consumer. Do not run multiple Mac workers against the same queue until claim operations have a server-side compare-and-swap/lease mechanism.

## Security requirements

- Queue repository must remain private.
- Use a dedicated least-privilege GitHub credential scoped only to the queue repository's Issues read/write operations; do not reuse a broad personal token if a fine-grained token can be used.
- Store credentials only in Render secrets / macOS Keychain or the user's existing secure GitHub CLI credential store. Never commit or log them.
- Authenticate Render's enqueue endpoint with the existing internal key and independently enforce the existing LINE development-user allowlist.
- The worker must reject unknown users, malformed tasks, oversized instructions, expired claims, and tasks lacking the required approval marker.
- Never auto-merge or deploy from the local worker. Return a PR and evidence; retain explicit human approval for merge/deploy.
- Do not expose Bonsai, Hermes, Cua, or the Mac desktop through a public inbound port.
- Redact secrets and avoid copying full LINE conversation history into GitHub Issues.

## Recovery and audit

- Every task has a stable request ID and immutable origin metadata.
- Claims have a bounded lease; a stale claim is returned to pending only after checking that no active worker still owns it.
- Completion records include exact commit SHA and exact-SHA test status. Runtime completion alone is not PASS.
- Keep failed/blocked issues open with diagnostic comments; do not silently discard them.

## Rollout gates

1. Review and merge the queue protocol implementation only after tests cover auth, allowlist, duplicate delivery, claim collision, stale-claim recovery, malformed payloads, and secret redaction.
2. Deploy the Render enqueue path without changing the LINE webhook URL.
3. Configure the Mac worker in read-only/dry-run mode first.
4. Verify one end-to-end task and its audit trail.
5. Enable execution only after the user explicitly approves the rollout.

## Current status

This document records the architecture decision only. It does not change the live Render service, LINE webhook, GitHub secrets, Hermes Gateway, or Mac permissions. The existing queue prototype PR #1 remains unmerged and must not be treated as production-ready.