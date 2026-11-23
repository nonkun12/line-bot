# AI Factory Stages 301–305: Distribution, Missingness and Lineage

- **301 — Score-distribution stability:** compares baseline/candidate first and second moments under declared tolerances.
- **302 — Domain-mix shift:** compares declared domain proportions using total-variation distance.
- **303 — Missingness sensitivity:** computes a conservative adjusted mean under a declared worst-case score for missing observations.
- **304 — Evidence lineage:** validates an ordered, hash-linked record chain from a declared root.
- **305 — Integrated evidence readiness:** requires all four sealed checks and yields separate-review eligibility only.

## Limitations

Scores, domain labels/counts, missingness fractions, worst-case assumptions, root digests and lineage records are caller-supplied. First/second moments do not establish full distribution equivalence. Domain mix checks do not establish representative sampling. Missingness sensitivity depends on a declared assumption and does not identify the missingness mechanism. Hash chains do not prove trusted custody, timestamps, source authenticity or actor identity. No causal improvement, RSI or ASI is proven.

## Safety

Evidence/proposal-only. No task execution, experiment, model change/training, HOLD release, merge or deployment is authorized.
