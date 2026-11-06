# Hermes local worker queue via private GitHub Issues

## Decision

Use GitHub Issues in the private nonkun12/ai-dispatch-queue repository as the durable hand-off between the existing Render LINE webhook and the Mac-local Hermes worker.

Do not deploy the current in-memory HTTP queue prototype from PR #1. Its process-local list is lost on restart, it has no authentication, and it does not provide a safe claim/lease protocol.

## Data flow

1. Keep LINE Developers Console pointed at the existing Render endpoint: https://line-bot-yvea.onrender.com/callback.
2. Render validates the LINE event and the existing development-user allowlist.
3. Render creates one issue in the private queue repository. The issue contains a request ID, bounded instruction, requesting LINE user ID, creation time, and an explicit approval state. Do not include channel secrets, access tokens, or unrelated chat history.
4. A single Mac-local worker polls the private repository outbound using an authenticated GitHub API session. No inbound tunnel to the Mac is needed.
5. A non-blocking macOS process lock prevents two local worker processes from running at once. Before claiming, the worker re-reads the issue and requires both approval_state: approved and queue_state: pending.
6. The first claim implementation updates the issue body to queue_state: claimed and records worker_id/claimed_at. It does not execute the instruction. GitHub Issues does not provide a compare-and-swap claim in this implementation, so only one designated Mac worker may be enabled; do not run another worker on another host.
7. Execution, result comments, closing issues, and LINE result delivery remain disabled until separately implemented and reviewed.

## Queue states

- pending: accepted and waiting for explicit approval.
- claimed: reserved by the single designated Mac worker; claim alone does not execute.
- running: execution started (not implemented yet).
- completed: completed with exact-SHA verification evidence (not implemented yet).
- blocked: approval, authorization, or safety gate prevented execution.
- failed: execution failed; preserve logs and retry metadata (not implemented yet).

The current local file lock protects only processes on the same Mac. It is not a distributed lock and does not prevent another host from racing the GitHub issue update. Keep exactly one designated worker host until a server-side compare-and-swap/lease mechanism exists.

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

The PR now contains a read-only poller and an explicit-approval claim function protected by a same-Mac process lock. Task execution and LINE delivery are still not implemented. No live Render service, LINE webhook, GitHub secrets, Hermes Gateway, or Mac permissions were changed. The existing queue prototype PR #1 remains unmerged and must not be treated as production-ready.