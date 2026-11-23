# AI Factory Stages 331–335: Longitudinal Stability and Generalization

- **331 — Temporal-window stability:** requires all declared time windows to exceed a gain floor and bounds best-to-worst spread.
- **332 — Distribution-shift robustness:** requires every declared shifted scenario to remain within a shift bound and exceed a gain floor.
- **333 — Bounded measurement perturbation:** subtracts a declared per-task error bound and requires worst-case gains to pass.
- **334 — Subgroup gain gap:** requires every declared subgroup to meet a gain floor and bounds the maximum subgroup gain gap.
- **335 — Integrated gate:** requires all four sealed checks and yields proposal eligibility for separate review only.

## Limitations

All windows, shift magnitudes, gains, perturbation bounds, subgroup labels and membership are caller-supplied. The checks do not authenticate timestamps, distribution-shift measurement, perturbation calibration, subgroup membership, or future performance. Subgroup gain-gap bounds do not prove fairness or parity. Digests provide integrity linkage only, not trusted provenance or custody. No causal capability gain, RSI or ASI is demonstrated.

## Safety

Evidence/proposal-only. All execution flags remain false. No task execution, experiment, model change/training, HOLD release, merge or deployment is authorized.
