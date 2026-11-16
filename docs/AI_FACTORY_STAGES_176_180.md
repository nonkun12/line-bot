# AI Factory Stages 176-180: Merge Readiness

These stages extend the evidence-bound evolutionary model-merge pipeline from Stages 171-175. They prepare a candidate for a human decision; they do not perform a parameter merge.

## Stage 176 — Immutable artifact manifest
Bind the exact candidate artifact digest, parent artifact digests, Stage 174 selection digest, evaluation-suite digest, and adjacent source/proposed generation numbers into one canonical manifest digest. Missing, duplicate, malformed, or non-adjacent lineage fails closed.

## Stage 177 — Independent reproducibility
Require repeated signed reruns against the exact manifest, candidate bytes, and evaluation suite. Every rerun must have a distinct executor and evaluator identity. Output digests must match for the reproducibility gate to pass. Replays, signature failures, and input drift are rejected.

## Stage 178 — Local resource feasibility
Compare measured RAM, disk, and compute time with explicit finite limits. Only local execution is eligible. Paid API use and cloud fallback are prohibited. A failed envelope remains a proposal-level failure; no job is launched.

## Stage 179 — Holdout and adversarial evaluation
Require signed evidence from a separate holdout suite, with a minimum case count, configured pass-rate threshold, and zero critical failures. Holdout evidence must bind to the Stage 176 manifest and cannot reuse the selection suite.

## Stage 180 — Human approval package
Package the manifest, reproducibility report, resource envelope, holdout assessment, candidate identity, proposed generation, and rollback artifact digest. The package may be marked ready for human review only when every gate passes.

## Authority boundary
All five stages are proposal-only. They do not load or execute model weights, mutate tensors, merge parameters, advance generation state, activate a model, or switch production. Stage 180 explicitly leaves human approval false and all execution/activation authority false. A separate, explicit human decision and separately governed execution workflow are required.
