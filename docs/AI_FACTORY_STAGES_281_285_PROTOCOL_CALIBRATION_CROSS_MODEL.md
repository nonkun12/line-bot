# AI Factory Stages 281–285: Protocol, Calibration and Cross-Model Evidence

- **281 — Protocol drift:** hashes canonical preregistered and observed protocol snapshots; any mismatch is flagged.
- **282 — Evaluator calibration:** compares evaluator scores with supplied reference labels and applies mean and maximum absolute-error limits.
- **283 — Sample adequacy:** requires unique task declarations, per-domain task quotas and declared stratum coverage.
- **284 — Cross-model reproducibility:** compares two model score sets on exactly matching domain/task pairs and per-task evidence digests.
- **285 — Evidence integration:** requires all four sealed checks to pass and emits eligibility for separate review only.

## Limitations
Protocol snapshots, reference labels, evaluator identities, task sets, model identifiers and scores are caller-supplied. A digest is not authentication or trusted timestamping. Calibration against supplied labels does not establish label correctness. Declared strata do not prove representativeness. Matching task evidence does not prove model independence or equivalent execution environments. Similar scores do not prove general capability gain, causal improvement, RSI or ASI.

## Safety
All stages fail closed unless HOLD is explicitly false. Task execution, experiment execution, model changes, merge/deploy and HOLD release remain false. Stage 285 is evidence integration only.
