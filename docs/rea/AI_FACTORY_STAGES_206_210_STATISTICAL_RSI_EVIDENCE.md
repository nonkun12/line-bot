# AI Factory stages 206-210: Statistical RSI evidence

These stages add evidence validators and conservative summaries only.

- **206**: paired sample mean and one-sided 95% lower confidence bound; requires 5+ pairs.
- **207**: executor/evaluator signer role separation; this is attestation-level separation, not proof of evaluator independence.
- **208**: control/treatment difference-in-means, requiring declared randomized or matched design; never authorizes causal claims.
- **209**: required-stratum coverage and per-stratum safety checks.
- **210**: RSI evidence gate combines positive lower bound, safety >= 0.95, reproducibility >= 0.90, evaluation cost ratio <= 1.10, and robustness support.

Trust boundary: caller must independently verify signature validity, data provenance, design registration, and attestation trust. The statistical helper assumes provided observations are valid and does not validate normality, distributional assumptions, multiplicity, sample independence, power, or preregistration. Small-sample t critical values are conservative tabulated approximations with interpolation by upper table bucket; for df beyond table, 1.645 is used. It is not a replacement for a statistical review.

All outputs are proposal-only. HOLD fails closed. No inference, training, weight/model activation, workflow dispatch, data mutation, merge, or deploy. No RSI or ASI is established by code alone.
