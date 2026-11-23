# AI Factory Stages 251–255: Artifact Integrity and Attestation Controls

These deterministic validators extend the evidence pipeline with checks over actual supplied artifact bytes, key-lifecycle declarations, replay tokens, and role separation. They are proposal-only and do not authorize execution.

- **251 — Artifact byte verification:** computes SHA-256 over actual byte strings supplied by the caller, rejects mismatches and duplicate artifact IDs, and derives a package digest.
- **252 — Key lifecycle structure:** validates unique key IDs, principal labels, active/revoked state, timezone-aware validity windows, and active-key time bounds.
- **253 — Replay check:** rejects malformed or already-listed nonces, invalid issuance/expiry windows, future-issued attestations, expired attestations, and malformed package digests.
- **254 — Role separation:** requires distinct declared principals for issuer, evaluator, and approver roles.
- **255 — Attestation review gate:** integrity-checks the prior stage results and package linkage before recommending separate review.

## Critical trust limitations

- **No cryptographic signature verification is implemented.** Stage252 validates caller-supplied key lifecycle metadata only; it does not verify Ed25519, RSA, ECDSA, or HMAC signatures and does not establish that a key belongs to a real principal.
- The key registry is supplied to the function by its caller. Its digest is not rooted in an external trust anchor, signed registry, transparency log, or hardware-backed key store.
- Stage253 checks a caller-supplied consumed-nonce list. It is not durable, atomic, globally shared, or race-safe; a production replay defense requires a trusted persistent store with uniqueness/transaction guarantees.
- Stage251 hashes actual bytes present in memory at validation time, but does not fetch remote artifacts, establish source authenticity, or guarantee that the supplied bytes are the original evidence.
- Stage254 checks distinct principal strings only. It cannot prove organizational independence, prevent collusion, or authenticate role holders.
- Passing these stages is a structural readiness signal for independent review, not cryptographic attestation, execution approval, causal evidence, recursive self-improvement, or ASI.
- Every stage requires HOLD to be explicitly false. All task/experiment/model-change/merge-deploy/HOLD-release authority flags remain false. No experiments, training, model mutations, HOLD releases, merges, or deployments are performed.

## Required production-grade follow-up

Before treating attestations as trusted evidence, integrate a separately reviewed cryptographic verifier, externally anchored signer registry and revocation source, immutable/atomic nonce store, authenticated artifact retrieval, and independently administered evaluator identities. Those integrations are intentionally not simulated by these validators.
