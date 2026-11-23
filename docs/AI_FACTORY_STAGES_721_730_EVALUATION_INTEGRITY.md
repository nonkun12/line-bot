# AI Factory Stages 721–730: Evaluation Integrity and Reproducibility

This stage adds a fail-closed evidence envelope around capability-evaluation
claims. It validates declarations and formats; it does not verify their truth.

- 721: canonical evaluation manifest and root-digest declaration.
- 722: artifact inventory with per-artifact SHA-256 declarations.
- 723: runtime, dependency, hardware, and configuration fingerprint declaration.
- 724: issuer/subject/key/signature attestation metadata.
- 725: evaluator independence and conflict-of-interest declarations.
- 726: preregistered statistical analysis plan and declared outputs.
- 727: reproduction package, pinned dependencies, seeds, and expected outputs.
- 728: independent reproduction attempt and output-comparison declarations.
- 729: ordered provenance events and chain references.
- 730: integrated external-verification gate.

The implementation deliberately does not retrieve artifacts, recompute hashes,
verify signatures, authenticate people or keys, recalculate statistics, execute
reproduction, or verify provenance chains. A complete record is only
READY_FOR_EXTERNAL_VERIFICATION.

## Safety boundary

No capability improvement is certified. No model weights/configuration are
changed, and no deployment or production action is authorized. Caller-provided
metadata and cryptographic-looking strings are not independent evidence.
