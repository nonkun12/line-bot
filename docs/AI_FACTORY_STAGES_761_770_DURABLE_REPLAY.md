# AI Factory Stages 761–770: Durable Replay Protection

- 761: persistent replay-ledger contract and explicit namespace.
- 762: SQLite reference implementation with schema versioning and WAL.
- 763: atomic nonce insertion under BEGIN IMMEDIATE and unique constraint.
- 764: issuer/consumer namespace isolation.
- 765: expiry-based stale nonce cleanup.
- 766: concurrent duplicate-consumption tests.
- 767: key lifecycle validation (active/revoked, validity window, key version).
- 768: SQLite integrity check and audit-chain verification.
- 769: transactional, redacted hash-linked audit event with nonce consumption.
- 770: fail-closed integration gate; no authorization is granted.

## Operational and security boundaries

SQLite is a local reference implementation, not a distributed consensus service.
The caller must provide a persistent path, protect filesystem access, back up the
database, and operate it on storage with appropriate durability. The module does
not configure OS permissions, encryption at rest, backup restoration, replication,
or external audit anchoring. The hash chain detects inconsistency relative to its
stored history but is not tamper-proof if an attacker can rewrite the database.

Key lifecycle validation is a helper and must be composed with the cryptographic
verification policy by the caller. This module does not store keys, authenticate
key custodians, or rotate keys automatically. A replay-protected result is not
permission to mutate models, code, deployments, or production state.
