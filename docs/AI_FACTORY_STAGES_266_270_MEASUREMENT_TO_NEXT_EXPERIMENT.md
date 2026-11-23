# AI Factory Stages 266–270: Measurement-to-Proposal Pipeline

These stages connect task-bank integrity and evaluation records to a proposal-only next-experiment shortlist.

## Stages

- **266 — Task-bank manifest:** hashes the actual supplied task payload bytes, records byte lengths and domains, rejects duplicate task IDs, and checks minimum per-domain coverage.
- **267 — Preregistration ledger:** validates a contiguous sequence of hash-linked preregistration events with timezone-aware ISO-8601 timestamps.
- **268 — Runtime fingerprint:** captures selected facts from the current Python process (implementation/version, platform, machine, processor, CPU count, byte order and floating-point precision) and binds them to a canonical runtime-configuration digest.
- **269 — Multi-domain aggregation:** requires every domain to meet its own sample minimum and exceed its own practical-gain lower-bound threshold. A strong domain cannot conceal a weak or regressed domain.
- **270 — Next-experiment proposal ranking:** ranks only candidates with sealed multi-domain evidence and sealed independent-replication evidence. Ranking is by worst-domain lower bound, then macro mean. Output is a proposal, never an execution request.

## Evidence boundaries

- Stage266 proves only the bytes supplied to this function were hashed. It does not prove the task bank is hidden, representative, licensed, independently curated, or unchanged before receipt.
- Stage267 is a local hash chain. It does not provide a trusted timestamp, remote append-only transparency log, digital signatures, or authenticated actor identity.
- Stage268 fingerprints the current Python process and selected host-visible properties. It does not introspect model weights, GPU kernels, hidden prompts, external services, or prove two model executions were equivalent.
- Stage269 expects already validated, direction-adjusted per-domain statistical estimates. It does not independently recompute raw paired scores or repair weaknesses in upstream estimates.
- Stage270 only ranks evidence packages. Candidate IDs and upstream evidence remain caller supplied; a ranking is not proof of generalization, autonomous self-improvement, RSI, or ASI.
- SHA-256 digests provide content-integrity checks, not authenticity or authorization.

## Safety

All stages fail closed unless HOLD is explicitly false. Proposal-only and all task execution, experiment execution, model mutation, merge/deploy, and HOLD-release authority flags remain false. No experiments, training, model execution, weight changes, merge, deployment, or HOLD release are performed.
