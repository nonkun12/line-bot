# AI Factory Stages 186–190 — Multi-generation Evolution Integrity

Stages 186–190 extend the Stage 181–185 inter-generation readiness pipeline. They improve longitudinal evaluation, holdout auditing, regression diagnosis, survival knowledge retention, and evidence packaging. Outputs remain proposal-only.

## Stage 186 — Longitudinal trend analysis
- Requires a signed Stage 185 readiness checkpoint, matching starting generation, and candidate-lineage verifier.
- The Stage 186 module exposes `stage185_checkpoint_verifier`, an adapter over the signed Stage 185 certificate. It verifies the certificate digest/signature, proposed generation, candidate membership, and proposal-only authority flags.
- Each generation snapshot is signed over a canonical digest and chained to the prior snapshot; the first snapshot chains to the Stage 185 checkpoint.
- Uses a fixed suite digest, unique evaluator/trial identities, and a distinct executor identity.
- Consumes at most 33 items to enforce the 32-snapshot cap before materialization.
- Reports quality, safety, latency, and memory deltas with explicit regression flags.

## Stage 187 — Generalization and contamination audit
- Re-verifies the Stage 186 signature and the evidence signature.
- Requires distinct training/holdout digests, explicit disjointness and non-use attestations, a contamination check, and minimum coverage.
- The holdout evaluator must differ from every Stage 186 evaluator and executor.

## Stage 188 — Regression attribution
- Re-verifies the Stage 186 and Stage 187 reports.
- Accepts at most 64 signed claims with candidate and generation lineage.
- The diagnostician must be independent of the executor, trend evaluators, and holdout evaluator.
- Unknown or unsupported causes remain explicitly unsupported. The report digest binds every signed claim, including unsupported claims; duplicate/replayed claims are rejected before classification, and Stage 190 requires canonical sorted claim-digest ordering.

## Stage 189 — Append-only survival ledger
- Requires a trusted current predecessor digest/generation checkpoint and individually signed entries.
- Consumes at most 129 items before enforcing the configurable maximum (1–512).
- Requires contiguous generations, known outcomes, unique generation/candidate/strategy keys, and a digest-chained signed ledger proposal.
- The predecessor verifier must be read-only and reject stale/replayed checkpoints; this stage does not advance checkpoint state.

## Stage 190 — Multi-generation integrity certificate
- Re-verifies all report and entry signatures, canonical digests, predecessor trust, and cross-stage lineage.
- Requires the ledger to start at the trend baseline and cover every subsequent generation through the trend window.
- Packages a review-only certificate. All weight, generation, activation, and production authorization flags remain false.

## Signature contract
- Each stage verifies the signature it emits before returning its report, ledger, or certificate.

## Safety and execution boundary
HOLD blocks every stage. Invalid signatures, missing evidence, replay, gaps, tampering, evaluator overlap, lineage drift, or resource-bound violations fail closed. No inference execution, tensor/weight mutation, parameter merge, generation-state advancement, model registration/activation, production switch, permission change, merge, or deployment is performed. No paid API or cloud fallback is introduced.

The Stage 185 checkpoint verifier and Stage 189 predecessor verifier are trusted read-only callbacks. They must check the current trusted checkpoint and reject stale/replayed digests; the proposal builders do not mutate checkpoint state.


## Follow-up integrity hardening
- Stage 186 binds the frozen metric-threshold policy into the signed trend digest and rejects caller-supplied thresholds weaker than the minimum safety/quality/latency/memory policy.
- Stage 187 binds its minimum holdout-coverage policy into the signed audit digest and rejects coverage thresholds below 95%.
- Stage 190 revalidates the trusted Stage 185 checkpoint at certificate time, preventing stale checkpoint replay between trend creation and packaging.
- Stage 190 independently enforces the 32-snapshot, 64-diagnostic, and 512-ledger-entry collection bounds before expensive validation; evidence collections must be immutable tuples.


## Upstream Stage 171–185 hardening and connection
- Stage 171–175 now re-compute combination, compatibility, candidate-evaluation, report, and selection digests before downstream use.
- Stage 173 accepts at most 256 trial records and requires complete compatibility coverage, typed evidence, distinct repeat evaluators, and stable candidate artifact identity.
- Stage 181 accepts at most 64 candidate evaluations; Stage 182 bounds recipe iteration before materialization; Stage 183 requires typed, bounded evaluation evidence.
- Stage 185 includes the eligible/selected candidate identities in its readiness digest and can emit a signed checkpoint. Unsigned legacy certificates remain usable for review display but are rejected by the Stage 186 adapter.
- Stage 186 consumes that certificate through `stage185_checkpoint_verifier`; no manual digest-only trust shim is required. The connection validates candidate identity and generation, not merely digest equality.
