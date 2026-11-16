# ORCA RSI trust attestation schema v1

Status: **VERIFIER AND FIVE-STAGE GATE INTEGRATION IMPLEMENTED IN CODE; TRUST SERVICES AND PRODUCTION PROVISIONING NOT IMPLEMENTED**

The five-stage continuation gate now requires three actual signed claims:
independent review, task approval, and budget authorization. It verifies and
consumes each claim through its own pre-provisioned replay ledger, passing the
latest CAS snapshot forward after every successful write. Caller-supplied
`approval_verified` and `budget_verified` booleans are not accepted.

This is not production authorization. No independent signing service, trusted
public-key configuration, human approval service, budget evidence collector,
or production replay-state document has been provisioned. The gate returns
`execution_started=false`; no worker is started by this integration. Tests
have been added, but their execution and CI result must be verified separately.

This document defines the trust boundary required before an RSI worker may execute
a queued task. It does not authorize execution, create signing keys, provision
GitHub secrets, initialize durable state, enable a workflow schedule, or change
the current fail-closed behavior.

## 1. Trust roles

Three independent Ed25519 trust domains are required:

| Domain | Purpose | Private-key owner | Worker receives |
|---|---|---|---|
| Review | Independent PASS review | Reviewer service, independent of implementer | Public key + reviewer allowlist |
| Task approval | Explicit approval of one immutable task | Human approval authority | Public key + approver allowlist |
| Budget authorization | Authorize a bounded spend for one task/cycle | Budget authority / trusted collector | Public key + issuer allowlist |

The three public keys, key IDs, allowlists, and replay ledgers MUST be distinct.
A reviewer key MUST NOT authorize tasks or budgets. A task approver MUST NOT
approve their own implementation. A budget issuer MUST NOT be inferred from a
worker-provided boolean or environment variable.

No signing service, key, allowlist, or budget collector is currently provisioned.
Until they are provisioned and independently verified, every execution preflight
MUST return BLOCKED.

## 2. Common envelope

Each signed claim is a UTF-8 JSON object with exactly the fields specified by
its schema below. Unknown or missing fields are rejected. Signatures use
Ed25519 over canonical JSON after removing only the `signature` field:

- UTF-8 encoding
- object keys sorted lexicographically
- separators `,` and `:` (no insignificant whitespace)
- `ensure_ascii=false`
- NaN and Infinity forbidden
- no duplicate JSON object keys at ingestion

The signed payload MUST include a purpose-specific `claim_type` and exact
`schema_version=1`. The verifier MUST check the key ID against the allowlist
for that claim type before accepting the signature. A trusted, separately
provisioned `key_id -> signer_id` mapping MUST bind each public key to exactly
one identity; the claim's `approver_id` or `issuer_id` MUST equal the identity
mapped to its `key_id`. A general signer allowlist alone is insufficient,
because it would let one allowed key assert another allowed identity. The
review, approval, and budget key-to-identity maps MUST remain separate. No
truthy/falsy coercion is permitted; booleans are not integers.

All timestamps are timezone-aware RFC 3339 UTC strings ending in `Z`.
Claims are short-lived, have explicit `issued_at` and `expires_at`, and are
rejected if expired, issued too far in the future, or outside the configured
maximum lifetime. The verifier's clock is trusted runner time, not claim time.

Every claim has a cryptographically random nonce (at least 128 bits, encoded
as 32 or more lowercase hexadecimal characters). The nonce and SHA-256 hash
of the complete signed claim are consumed atomically in the durable state store
using compare-and-swap. A failed CAS blocks; never retry with a fresh snapshot
inside the same attempt.

## 3. Task approval claim

Exact required fields:

| Field | Type / rule |
|---|---|
| `claim_type` | exact string `orca_rsi_task_approval` |
| `schema_version` | exact integer `1` |
| `key_id` | non-empty allowlisted approval key identifier |
| `repository` | exact `owner/name` |
| `task_id` | exact queued task identifier |
| `task_digest` | lowercase SHA-256 hex of canonical immutable task payload |
| `cycle_id` | lowercase SHA-256 hex cycle identifier |
| `commit_sha` | exact 40-character lowercase Git commit SHA |
| `approver_id` | non-empty identity in the approval allowlist |
| `verdict` | exact string `APPROVED` |
| `nonce` | unique random nonce |
| `issued_at`, `expires_at` | UTC timestamps; maximum lifetime 10 minutes |
| `signature` | base64-encoded 64-byte Ed25519 signature |

The verifier MUST compare repository, task ID, task digest, cycle ID, and commit
SHA with the live durable queue item and current run. A task ID alone is not a
sufficient binding. The task digest is computed from the exact immutable task
payload using the common canonicalization rules. Any payload mutation requires
a new approval.

The approval authority MUST be human-controlled and separate from the worker.
The worker MUST NOT mint or rewrite approval claims. The review verifier MUST
also receive both the review-key-bound `public_key_reviewer_id` and the
implementer identity from trusted orchestration configuration. It MUST reject
any mismatch between `reviewer_id` and `public_key_reviewer_id`, and reject
`reviewer_id == implementer_id`; a caller-provided identity
string without a trusted binding is not sufficient. Missing approver identity,
unknown key ID, non-APPROVED verdict, stale claim, digest mismatch, or replay
means BLOCKED.

## 4. Budget authorization claim

Exact required fields:

| Field | Type / rule |
|---|---|
| `claim_type` | exact string `orca_rsi_budget_authorization` |
| `schema_version` | exact integer `1` |
| `key_id` | non-empty allowlisted budget key identifier |
| `repository` | exact `owner/name` |
| `task_id` | exact queued task identifier |
| `task_digest` | lowercase SHA-256 hex of canonical immutable task payload |
| `cycle_id` | lowercase SHA-256 hex cycle identifier |
| `commit_sha` | exact 40-character lowercase Git commit SHA |
| `issuer_id` | non-empty identity in the budget issuer allowlist |
| `budget_unit` | configured fixed unit identifier; never inferred |
| `authorized_limit_units` | exact integer greater than zero |
| `observed_spend_units` | exact integer greater than or equal to zero |
| `remaining_units` | exact integer greater than or equal to zero |
| `evidence_refs` | non-empty list of immutable evidence identifiers |
| `evidence_sha256` | lowercase SHA-256 hex digest of the collected evidence bundle |
| `nonce` | unique random nonce |
| `issued_at`, `expires_at` | UTC timestamps; maximum lifetime 5 minutes |
| `signature` | base64-encoded 64-byte Ed25519 signature |

The verifier MUST enforce:
- `observed_spend_units + remaining_units <= authorized_limit_units`;
- the configured unit is exact and consistent across collector and worker;
- all integer fields use `type(value) is int` (reject booleans and floats);
- evidence references resolve to immutable collector evidence and the bundle
  digest matches the retrieved bytes;
- the claim is bound to the exact repository, task, task digest, cycle, and
  commit being considered.

A caller-supplied `budget_verified=true`, a self-reported balance, an absent
collector, or an unresolvable evidence reference is never evidence.

## 5. Durable replay state

The durable state document must maintain separate ledgers:

- `rsi_review_replay`
- `rsi_task_approval_replay`
- `rsi_budget_authorization_replay`

Each ledger contains parallel, unique arrays `used_nonces` and
`used_attestation_hashes`. Both arrays must have equal lengths and valid
entries. Claim verification and replay consumption are one logical gate;
consumption uses the existing GitHub state store's non-force revision CAS.
Missing branch/document, missing individual ledger, malformed ledger, full ledger,
network error, or CAS conflict blocks the attempt. All three ledger objects must
already exist in the provisioned state document; claim consumption must never
create a missing ledger. Do not initialize or clear a missing state ref.

## 6. Catalog candidate flag is not execution approval

The legacy task-catalog field `execution_approved: true` is treated only as a
candidate-discovery/triage flag by the read-only preparation loop. It MUST NOT
be interpreted as human authorization to execute code. Preparation reports
expose it as `catalog_candidate_flag`, explicitly set
`execution_approved=false`, and set `human_execution_approval_required=true`.
A separate signed task-approval claim bound to the immutable task digest,
cycle, commit, and repository is mandatory before any execution authorization.
This distinction applies even when task instructions say "after human review".

## 7. Execution preflight contract

A future preflight may return `READY` only if all of the following are true:

1. RSI five-stage cycle is complete and final result is PASS.
2. Global HOLD, emergency stop, and kill switch are all explicitly false.
3. Exactly one allowlisted queued task is selected and its immutable digest
   matches the durable task record.
4. No active worker lease exists; a lease is acquired atomically before launch.
5. Independent review, task approval, and budget claims all verify and are
   consumed once through durable CAS.
6. Reviewer is independent of task implementer and approver; task approver and
   budget issuer identities satisfy their separate policies.
7. The current repository, task, task digest, cycle, and commit match every
   claim; reviewer identity is independently bound to its review key and is
   distinct from the trusted implementer identity.
8. Required evidence is retrievable and content digests match.

The preflight result is advisory authorization only. It MUST return
`execution_started=false`. A separate worker adapter must re-read safety
state, atomically acquire the task lease, and only then invoke an allowlisted
handler. Missing handler, unsupported task, stale state, or any exception
must produce BLOCKED without invoking a subprocess or modifying source.

## 8. Required negative tests before integration

For each claim type, tests MUST demonstrate BLOCKED for: missing claim, unknown
fields, duplicate JSON keys, malformed signature, wrong key or key ID, expired
claim, future timestamp, invalid timezone, wrong repository/task/task digest/
cycle/commit, wrong claim type, unsupported schema, non-allowlisted identity,
replayed nonce, replayed claim hash, malformed durable ledger, CAS conflict,
and missing evidence.

Additional budget tests: booleans/floats/negative values, mismatched units,
overspend, arithmetic boundary cases, missing collector evidence, unresolved
references, and evidence digest mismatch.

Additional approval tests: verdict other than APPROVED, task payload changed
after approval, approval by the implementer, and approval for another task.

Integration tests MUST prove that the worker handler is never called when any
claim is missing/invalid, any safety stop is active, state is unavailable, a
lease is active, or the task handler is not allowlisted.

## 9. Provisioning and rollout gates

Before implementation can be connected to a worker, the project owner must
explicitly choose and provision:

- approval authority identity and signing service;
- budget authority identity, unit, trusted collector, and immutable evidence
  retrieval mechanism;
- three separate public keys, key IDs, allowlists, rotation/revocation policy;
- durable `orca-state` branch and state document, created through a separately
  reviewed provisioning process;
- implementer identity source and reviewer/approver independence policy.

No workflow schedule is added by this specification. The autonomous workflow
must remain manual-only until the complete trust chain and negative integration
tests are reviewed. This document does not authorize merge, schedule activation,
patch application, or deployment.
