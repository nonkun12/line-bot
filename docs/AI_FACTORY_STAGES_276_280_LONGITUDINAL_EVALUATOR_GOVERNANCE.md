# AI Factory Stages 276–280: Longitudinal and Evaluator Governance

- **276 — Capability history:** creates hash-linked records from sealed passing regression guards. This is a verifiable local chain, not externally append-only storage or trusted timestamping.
- **277 — Evaluator disagreement:** requires unique evaluator declarations, three or more scores per domain, and flags score spreads above a configured limit.
- **278 — Improvement durability:** checks chronological observations and detects excessive score decay per domain over follow-up observations.
- **279 — Measurement-bias screen:** flags declared subgroup score gaps. The implementation cannot prove subgroup completeness, representativeness, or correct stratification.
- **280 — Unified evidence-governance gate:** requires valid sealed history, evaluator agreement, durability, and subgroup-gap results. It returns eligibility for separate review only.

## Limitations
Evaluator IDs, timestamps, subgroup labels, evidence digests and scores are caller supplied. Hash chains do not provide trusted time, remote custody, actor authentication, or protection against a caller rewriting the entire chain. Multiple evaluator IDs do not prove evaluator independence. Longitudinal scores do not prove causal improvement or generalization. Subgroup checks only cover declared groups. None of these stages proves RSI or ASI.

## Safety
All stages fail closed unless HOLD is explicitly false. Task execution, experiment execution, model changes, merge/deploy and HOLD release remain false. The unified gate is evidence governance only and never authorizes an experiment or model update.
