# AI Factory Stages 191–195 — Reproducible Capability Benchmarks

## Purpose

Provide a deterministic, evidence-based way to compare a baseline model artifact with a challenger artifact. These stages measure supplied model-run evidence; they do not execute models or change model parameters.

## Stage contracts

- **191 — Frozen suite:** canonical, sorted, content-addressed benchmark cases; typed records, unique IDs, signed suite digest, maximum 256 cases.
- **192 — Run evidence:** complete signed evidence from an external runner; every case appears exactly once; finite quality, safety, latency, and memory metrics; executor and evaluator identities differ.
- **193 — Paired comparison:** baseline and challenger use the identical frozen suite. Weighted quality gain must be at least 0.01; challenger safety must remain at least 0.95 with no safety decline; latency and memory growth must each remain at or below 10%.
- **194 — Repeatability:** at least three distinct signed comparisons; comparison payload digests are recomputed before aggregation; every repeat must pass.
- **195 — Capability decision:** emits CAPABILITY_GAIN_SUPPORTED only from a valid Stage 194 certificate.

## Trust boundaries and limitations

The benchmark runner, evaluator, signing keys, dataset provenance, and hardware telemetry are external trust inputs. A valid signature proves that the configured signer attested to a digest; it does not independently prove sandbox isolation, dataset quality, or that an authentic model executed. Those provenance controls must be supplied and independently audited before treating results as scientific evidence.

A supported capability gain means only that the signed benchmark evidence passed this defined repeatability and regression policy. It is not proof of general intelligence or ASI.

## Safety

All stages fail closed on HOLD, malformed evidence, replay, incomplete suite coverage, invalid signatures, and weakened thresholds. Outputs are proposal-only. Model activation, weight mutation, generation advancement, merge, and deployment authorization remain false. No paid API, cloud fallback, model execution, or production write is introduced.
