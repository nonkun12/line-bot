# AI Factory Stages 201-205 — Longitudinal Capability Trends

## Purpose

Stages 201-205 turn individually signed benchmark snapshots into a conservative, multi-generation trend signal. They are designed to support objective measurement of iterative capability improvement (an RSI-related engineering signal), not to assert that recursive self-improvement or ASI has been achieved.

## Contracts

- **201 — Capability snapshot:** signs one generation's model artifact digest, frozen suite and dataset digests, environment digest, provenance-certificate digest, evaluator identity, and quality/safety/latency/memory metrics.
- **202 — Generation lineage:** requires at least three consecutive generations, unique snapshot IDs, distinct artifact digests, valid signatures, and an unchanged benchmark suite, dataset, and environment.
- **203 — Trend analysis:** compares the first and last measurements and checks every intermediate safety score.
- **204 — Regression guardrails:** requires quality gain >= 0.01, safety >= 0.95 at every generation, no safety regression, and latency/memory growth <= 10%.
- **205 — RSI trend certificate:** emits CAPABILITY_TREND_SUPPORTED only when the preceding evidence meets every gate. Otherwise it emits INSUFFICIENT_OR_REGRESSING_EVIDENCE.

## Trust and limitations

Signatures prove that configured signers attested to supplied digests; they do not independently prove model execution, evaluator independence, dataset suitability, hardware identity, or causal attribution. The provenance certificate digest is an input and must be independently verified by the caller against the Stage 196-200 trust root. The nonce must be checked against a persistent replay registry outside this module. Keeping suite, dataset, and environment fixed reduces confounding but does not eliminate all confounders.

This module does not run inference, modify weights, activate models, dispatch workflows, change production state, merge, or deploy. All outputs are proposal-only. A trend signal is not proof of general intelligence or ASI.
