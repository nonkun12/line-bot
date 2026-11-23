# AI Factory Stages 711–720: Capability Evaluation Evidence

Introduces a fail-closed, metadata-only package for evaluating claims of model or
system capability change against a declared baseline.

- 711: bind evaluation subject, candidate, baseline, and audit record.
- 712: freeze protocol, version, environment, and command references.
- 713: define metrics, units, direction, baseline/candidate values, and acceptance rules.
- 714: bind dataset version, provenance, split, and license declarations.
- 715: bind run inputs, outputs, environment, and result evidence.
- 716: require independent replication declarations.
- 717: require regression-check evidence.
- 718: record uncertainty method, interval, and assumptions.
- 719: require independent assessment and explicit limitations.
- 720: integrated fail-closed capability-evaluation gate.

Every input is caller-supplied metadata. Numeric values are checked for finite
representation, but not recomputed or verified. The gate does not run benchmarks,
models, statistical tests, or replications. A complete package is only
READY_FOR_INDEPENDENT_REVIEW.

## What this does not prove

It does not establish measured capability improvement, general intelligence,
ASI, evaluator identity, dataset access rights, or reproducibility. It does not
authorize model changes, weight updates, deployment, or production operations.
