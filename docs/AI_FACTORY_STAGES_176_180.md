# AI Factory Stages 176-180 — Merge Readiness and Human Approval Package

These stages extend the evidence-bound evolutionary model-merge pipeline after Stage 175. They create a reviewable readiness package only; they do not run model merges or alter model weights.

## Stage 176 — Immutable artifact manifest
Creates a canonical SHA-256 manifest binding the selected candidate artifact, parent model IDs and artifact digests, Stage 172 compatibility evidence, Stage 173 evaluation report, Stage 174 selection, frozen evaluation suite, adjacent generation proposal, explicit licenses, provenance, and rollback artifact digest. Missing metadata, malformed digests, duplicate parents, or non-adjacent generations fail closed.

## Stage 177 — Independent reproducibility verification
Consumes signed attestations from bounded repeated runs. Every run must bind to the exact Stage 176 manifest, candidate artifact, and frozen suite. Run, evaluator, and executor identities must be distinct; signatures must verify; result and metrics digests must reproduce exactly. This stage verifies supplied evidence and does not execute a model.

## Stage 178 — Local resource feasibility
Compares declared CPU, RAM, VRAM, disk, runtime, and energy estimates against a local resource envelope. Paid API and cloud fallback must both remain disabled. Exceeding any limit yields an infeasible report; no fallback or resource provisioning is performed.

## Stage 179 — Holdout and adversarial robustness
Requires signed holdout evidence tied to the exact manifest, candidate artifact, and frozen suite. Evidence must attest that holdout data was not contaminated, use distinct evaluator identities, share a frozen holdout dataset and adversarial suite, and meet the minimum coverage threshold. Failed or incomplete evidence cannot pass.

## Stage 180 — Human approval package
Packages the manifest, reproducibility report, local resource report, holdout report, license identifiers, and rollback digest into a canonical readiness certificate. ready_for_human_review means only that the supplied evidence is internally consistent and gates passed. A separate human decision is still required.

## Safety boundary
All five stages are deterministic evidence validators and proposal producers. They do not execute candidate models, mutate tensors or weights, advance generation state, register or activate models, switch production traffic, change permissions, merge code, or deploy. HOLD blocks every stage. No cloud or paid API fallback is permitted.
