# AI Factory Stages 336–340: Protocol, Calibration and Freshness

- 336: compare required declared and observed protocol fields by canonical digest.
- 337: bound per-task evaluator score disagreement.
- 338: evaluate count-weighted calibration error over declared bins.
- 339: reject stale and future-dated evidence relative to a supplied reference timestamp.
- 340: sealed fail-closed integration gate; proposal eligibility only.

## Limitations
Inputs, evaluator IDs, confidence/accuracy values, timestamps and reference clocks are caller-supplied. Digests are not signatures or trusted commitments. Agreement does not establish evaluator independence. Calibration bins do not authenticate labels or samples. Freshness does not establish trusted time. No causal capability gain, RSI or ASI is demonstrated.

## Safety
All execution flags are false. No task execution, experiments, model changes/training, HOLD release, merge or deployment is authorized.
