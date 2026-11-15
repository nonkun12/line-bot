# Stage 141: evolutionary model merge planning

Stage 141 adds a bounded, metadata-only evolutionary planner. It does not
perform a tensor operation, download model files, invoke model endpoints, or
activate a candidate.

## Candidate strategies

- **Parameter merge** is eligible only when architecture, tokenizer fingerprint,
  tensor-schema fingerprint, artifact format, local artifact availability and
  license identifier match across all parents.
- **Adapter merge** additionally requires a shared, explicit adapter-base
  fingerprint.
- **Multi-model orchestration** is the safe fallback when parent architectures
  or formats differ. It is not described as a weight merge.

For example, Bonsai and LFM3 must not be assumed tensor-compatible. If their
metadata differs, Stage 141 produces an orchestration proposal, not merged
weights.

## Evolution and evaluation

Each proposal is evaluated against an identified evaluation-suite digest.
Fitness is multi-objective: accuracy, instruction following, safety, latency,
memory and regression count. Selection uses a Pareto frontier rather than a
single opaque weighted score. Candidates with safety below 0.95 or any
regressions are excluded.

## Safety boundary

- Kill switch, HOLD, evidence, budget and max-candidate gates fail closed.
- At most four proposals can be considered per tick; default is two.
- Parent model artifacts are immutable and are never read or modified here.
- Candidates are metadata-only, disabled, and PENDING_HUMAN_APPROVAL.
- No automatic approval, registration, activation, model-config change,
  deployment, merge, remote provider or paid API is used.
- Fitness values are supplied by an independent evaluator; this planner does
  not self-certify evaluation evidence.

The unit tests use synthetic descriptors and fitness fixtures. They do not
claim live Ollama, MLX, GGUF, Docker, or actual tensor-merge validation.
