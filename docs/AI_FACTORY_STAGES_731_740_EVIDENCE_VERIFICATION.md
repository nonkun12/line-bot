# AI Factory Stages 731–740: Evidence Verification

Moves beyond metadata-only declarations by adding bounded, local, deterministic
verification over explicitly supplied in-memory data.

- 731: canonical JSON serialization rules.
- 732: SHA-256 verification of supplied artifact bytes against inventory.
- 733: canonical manifest root-digest verification.
- 734: strict artifact inventory checks (missing, duplicate, unreferenced).
- 735: ordered provenance-chain digest and linkage verification.
- 736: numeric type and finite-value validation for metric arithmetic.
- 737: directional improvement and regression-threshold arithmetic.
- 738: tamper and malformed-input fail-closed tests.
- 739: integrated evidence-check report with per-check outcomes.
- 740: gate requiring additional signature, identity, and reproduction review.

## Scope and limitations

The verifier hashes only bytes explicitly passed by its caller; it does not
download or read repository artifacts. Canonical manifest and provenance digests
are recomputed. Metric arithmetic uses caller-supplied values and does not prove
that measurements are genuine or statistically significant.

Digital signatures, signer identity, evaluator identity, benchmark reruns,
dataset provenance truth, and independent reproduction are not verified.
Passing means only that these specific in-memory integrity checks passed.
It is not a capability certification, ASI proof, model-change approval, or
deployment authorization.
