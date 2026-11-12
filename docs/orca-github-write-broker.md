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

## Implementation progress: first slice

A separate Draft PR now implements the first slice in
`cloudflare/orca-test-api/src/write-broker.mjs`:

- A Durable Object stores Global HOLD and serializes its requests using
  `blockConcurrencyWhile`.
- The Worker reads HOLD from the Durable Object. Missing binding/state and
  transport failures remain blocked.
- HOLD transitions update D1 and the broker in fail-closed order: ON is set
  in the broker first; OFF is mirrored to D1 before the broker is released.
  HOLD release requires a separate operator credential plus operator ID and
  reason.
- One bounded operation is implemented: create a review Issue for a currently
  claimed, lease-valid, approved `app_development` task. The broker fixes the
  repository and does not accept client-selected labels; it mints a GitHub App installation token internally,
  and uses a persistent idempotency record. Uncertain outcomes are never
  retried automatically.
- Native Node contract tests cover initial HOLD, operator release, in-flight
  write vs HOLD ON ordering, idempotent replay, uncertain outcomes, invalid
  claims, and PKCS1 key handling. Wrangler local D1 integration tests now use
  the Durable Object binding and the explicit operator route.

This is **not** the full write broker migration. It does not yet broker
branch pushes, PR creation/updates, autonomous-state writes, Sheets, Render,
or LINE notifications. The legacy workflow still has direct GitHub write
paths. The HOLD drain guarantee applies only to operations that actually pass
through this Durable Object. Do not enable autonomous execution or remove
legacy write permissions until every required side effect has been migrated.

### Uncertain remote outcomes and DRAINING

A client timeout or GitHub 5xx does not prove that GitHub did not create an
Issue. Such outcomes are recorded as `uncertain` and automatically move the
broker to `DRAINING`. New broker writes are blocked. HOLD ON is **not**
acknowledged while any operation is `in_flight` or `uncertain`; the operator
must inspect GitHub using the embedded task/idempotency marker and submit a
separately authenticated manual reconciliation. After reconciliation, the
operator must explicitly acknowledge HOLD ON or deliberately release it.
If the durable operation ledger reaches its 1,000-record inspection ceiling,
the broker also fails closed for manual maintenance.

Every operator-initiated HOLD ON and OFF transition requires the separate
operator credential, an operator ID label, and a reason. The operator ID is
an audit label supplied by the authenticated caller; it is not an independently
verified GitHub identity.

The first Issue operation is limited to one per approved task; changing the
idempotency key cannot create a second Issue. The broker retains up to 100
recent HOLD audit events. The operation ledger inspection is capped at 1,000
records and fails closed at the ceiling, requiring operator maintenance.
