# ORCA GitHub Write Broker: serialized Global HOLD contract

## Why a preflight is insufficient

A GitHub Actions step that reads D1 and then calls GitHub has a TOCTOU window. Rechecking narrows that window but cannot make a D1 read atomic with a later GitHub API write. The current distributed-loop gates are defense in depth only; they are not a race-free authorization boundary.

## Proposed authority boundary

Introduce a Cloudflare Durable Object named `OrcaWriteBroker`, keyed by repository (one serialization domain per repository).

The broker, not the workflow, owns the GitHub write credential. Prefer a GitHub App installation token minted inside the Worker from narrowly scoped App credentials. Do not forward a broad `GITHUB_TOKEN` from Actions and do not expose a generic GitHub proxy.

The Durable Object must serialize *all* mutating operations and Global HOLD transitions through one FIFO critical section. Do not rely on JavaScript request handlers being serialized automatically; implement an explicit promise-chain/mutex and test concurrent requests.

### Allowed broker operations

Start with a closed allowlist, each operation with a schema and repository/path/branch constraints:

- create/update a bounded review Issue (if still required)
- create a task branch from the exact reviewed base SHA
- push a validated commit to the task branch
- create/update a Draft PR with fixed base branch
- update the allowlisted autonomous-state branch
- publish an allowlisted status snapshot

Reject arbitrary URLs, arbitrary HTTP methods, arbitrary GitHub API paths, force-push, merge, release, deployment, secret/permission changes, and any path outside the task's declared allowlist.

Each operation carries an idempotency key, task ID, claim/lease token, approved request hash, expected base/head SHA, and an operation-specific payload. The broker revalidates the task approval, task type, task limit, lease, Global HOLD state, and GitHub object state before making the one allowed API call.

## HOLD transition semantics (important)

A request to turn Global HOLD ON is queued in the same serialization domain as writes. It is acknowledged only after the currently executing broker operation finishes and the HOLD=ON state is durably stored. Any later queued write sees HOLD=ON and is rejected. Thus "HOLD acknowledged" means no earlier broker write remains in flight and no later broker write can start.

- Durable Object storage is authoritative for the broker gate; absent/corrupt state defaults to HOLD ON.
- D1 `system_controls` is a read/reporting mirror, not an independent write authority.
- All human HOLD ON/OFF changes must go through the broker control endpoint. Direct D1 edits, legacy workflows, and direct GitHub write credentials would bypass the serialization contract and invalidate the guarantee.
- HOLD OFF still requires an authenticated human operator and an auditable explicit action. No AI, timer, task completion, or worker may release HOLD.
- On DO eviction/restart, restore persisted state before serving writes. If restoration is unavailable or inconsistent with D1, fail closed and require operator reconciliation.

This gives a precise guarantee: after the broker acknowledges HOLD ON, no broker-mediated write is in flight or can begin. It cannot retroactively cancel a GitHub request that completed before the HOLD acknowledgement.

## Migration plan

1. Implement the Durable Object and concurrency/idempotency tests in a separate Draft PR.
2. Add a broker-only GitHub App with minimum repository permissions; store credentials only as Worker secrets.
3. Route every autonomous GitHub mutation through the broker. Remove direct write permissions from the distributed-loop workflow once broker operations are proven.
4. Route all Global HOLD changes through the same Durable Object; make D1 a mirror.
5. Test concurrent writes vs HOLD ON/OFF, duplicate idempotency keys, DO restart, unavailable storage, expired leases, stale SHAs, malformed operations, and unauthorized release.
6. Only after the end-to-end evidence is complete should the replacement executor be enabled. Keep #1331 and this PR unmerged until the cutover is explicitly approved.

## Current status

This document is a design contract only. No Durable Object, GitHub App, secret, D1 migration, production binding, deployment, or workflow permission change is created here. The preflight checks in PR #1340 remain defense in depth and must not be described as race-free.
