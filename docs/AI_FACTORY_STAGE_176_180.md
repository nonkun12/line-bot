# AI Factory Stages 176–180: Merge Readiness

These stages complete a review package for a potential evolutionary parameter merge. They do not perform a merge.

## Stage 176 — Immutable artifact manifest
Bind the exact candidate artifact, both parent identities and digests, frozen evaluation suite, selection digest, license, and adjacent source/target generation. The manifest is a digest-backed record only; it does not write or modify model artifacts.

## Stage 177 — Independent reproducibility
Verify supplied signed rerun attestations against the exact Stage 176 manifest, candidate digest, and evaluation suite. Require bounded repeated runs and distinct run, runner, and evaluator identities. Results must pass and produce the same result digest. The verifier does not launch jobs.

## Stage 178 — Local resource feasibility
Compare declared RAM, disk, runtime, and CPU estimates with an explicit local-only envelope. Paid APIs and cloud fallback are rejected. The gate does not reserve resources, run experiments, or infer hardware capacity.

## Stage 179 — Holdout and robustness
Require signed, distinct holdout evidence tied to the same candidate artifact and manifest. Safety, contamination, and robustness thresholds must all pass. Evidence is evaluated as supplied; no model execution occurs.

## Stage 180 — Human approval package
Bind the exact candidate and all prior report digests with license and rollback artifact digest. Produce a review certificate that explicitly requires separate human approval. The certificate itself grants no authority.

## Global invariants
- HOLD, kill switch, missing evidence, replay, lineage drift, or invalid signatures fail closed.
- All outputs are immutable proposals / evidence packages.
- No model execution, tensor/weight mutation, parameter merge, generation advancement, activation, or production switch.
- No paid API or cloud fallback.
- Actual model merge requires a separate human approval outside this pipeline.
