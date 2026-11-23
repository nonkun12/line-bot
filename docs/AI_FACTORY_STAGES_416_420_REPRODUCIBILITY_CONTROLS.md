# AI Factory Stages 416–420: Reproducibility Controls

## Scope
- **416 — Reproduction manifest:** required version/runtime/config declarations and unique input references with SHA-256-shaped digests.
- **417 — Artifact lineage:** run-to-input/output references and output digest-shape validation.
- **418 — Replay consistency:** detect conflicting output digests declared for the same case across runs.
- **419 — Execution environment:** require runtime, platform, dependency-lock digest, and seed-policy declarations per run.
- **420 — Aggregate gate:** fail-closed combination of the four validators and run/environment linkage checks.

## Safety and limitations
These validators inspect caller-supplied declarations; they do not execute experiments or replay jobs. A matching digest is a checksum, not a trusted signature or proof of origin. A declared runtime, dependency lock, seed policy, or input reference is not independently authenticated. Matching output digests do not establish semantic equivalence, determinism under all conditions, scientific reproducibility, or correctness. A mismatch is a useful blocker; a match is not proof of reproducibility.

The aggregate remains proposal-only. `execution_authorized` and `promotion_authorized` are always false. No experiments, training, model/weight changes, HOLD release, permission changes, production actions, merge, or deployment are performed. No RSI/ASI claim is made.
