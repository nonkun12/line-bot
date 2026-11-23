# AI Factory Stages 286–290: Longitudinal Robustness Gates

- **286 — Longitudinal stability:** chronological repeated observations and per-domain score-range limits.
- **287 — Regression budget:** rejects any domain regression beyond a predeclared tolerance.
- **288 — Evaluator consensus robustness:** median/MAD disagreement diagnostics with minimum evaluator counts.
- **289 — Holdout separation:** verifies digest-level disjointness and minimum holdout size.
- **290 — Integrated robustness gate:** requires all four sealed checks and returns eligibility for separate review only.

## Limitations
All observations, evaluator identities, scores, task digests and timestamps are caller-supplied. Hashes do not authenticate custody, timestamps, evaluator independence, task blinding or absence of prior exposure. A holdout digest check cannot prove the task bank is genuinely unseen or representative. These gates do not establish causal improvement, general capability gain, recursive self-improvement or ASI.

## Safety
Every stage is proposal/evidence-only. Task execution, experiments, model changes, merge/deploy and HOLD release remain unauthorized.
