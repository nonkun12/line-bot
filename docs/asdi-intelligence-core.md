# ASDI Intelligence Core

## Purpose

ASDI is the goal; a recurring LOOP is only one execution mechanism. The intelligence work must continue to produce useful, measurable artifacts even when every scheduled LOOP run is paused.

This foundation reuses the existing `core/` modules. It does not introduce another scheduler, model download, paid provider, automatic merge, or automatic deployment.

## Current repository capabilities

The following are present on the current `main` baseline:

- `core/multi_agent.py` and `core/agent_runtime.py`: bounded provider-neutral task contracts and serialized multi-agent runtime.
- `core/self_improvement.py`, `core/self_improvement_analyzer.py`, `core/self_improvement_cycle.py`, and `core/self_improvement_history.py`: bounded signals, recurring-pattern analysis, durable outcome memory, and reviewable improvement proposals.
- `scripts/run_guarded_runtime.py`: prior self-improvement evidence can be appended to a later task as explicitly untrusted context.
- `core/rsi_orchestra.py`: bounded RSI proposal and REA review hand-off.
- `core/rsi_independent_evaluator.py`: deterministic exact-match evaluation for locked held-out fixtures.
- `core/ai_factory_stage147_artifact_evaluation.py`, `core/ai_factory_stage156_authenticated_knowledge_transfer.py`, and `core/ai_factory_stage157_recursive_evolution_evaluation.py`: artifact checks, authenticated knowledge-transfer proposals, and longitudinal generation evaluation contracts.

These are useful foundations, not evidence that ASDI or autonomous model evolution is already achieved.

## Main integration gaps

1. The self-improvement cycle is primarily a report-to-proposal pipeline. It does not itself provide general research, multi-step reasoning, or verified knowledge retrieval.
2. Durable self-improvement memory is bounded and useful for recent feedback, but it is not yet a source-attributed, queryable knowledge base with contradiction handling and freshness.
3. RSI/evolution stages define strong evidence contracts, but the stages are not yet one end-to-end, routinely evaluated intelligence workflow.
4. `.github/workflows/hourly-self-improvement-sidecar.yml` is `workflow_dispatch` only. It is a report generator, not an independent autonomous intelligence process.
5. There is no single benchmark that measures the combined system's research accuracy, reasoning quality, memory retrieval, calibration, safety, and cost.

## Target architecture

Keep the core small and separate five responsibilities:

1. **Research** — gather source material and preserve source identity, timestamp, and exact supporting excerpts.
2. **Memory** — store validated facts, decisions, experiments, and outcomes with provenance, confidence, expiry/freshness, and links to contradictory evidence.
3. **Reasoning** — decompose a request into bounded subproblems, identify assumptions, compare candidate plans, and cite the evidence used.
4. **Evaluation (REA)** — independently score factual support, task completion, regression, safety, and uncertainty against a frozen test set.
5. **Improvement (RSI)** — convert measured weaknesses into small experiments; retain a change only when the same frozen evaluation suite demonstrates improvement without safety regression.

The orchestration layer passes typed artifacts between these components. It must not allow research content or memory records to become executable instructions.

## Operating modes

- **Offline analysis:** deterministic memory validation, history analysis, benchmark execution, and report generation. This mode requires no model provider and is useful while LOOP is stopped.
- **Advisory intelligence:** a configured model may propose research summaries, plans, or improvements. Outputs remain untrusted proposals until independently evaluated.
- **Controlled experiments:** candidate code/model artifacts are evaluated in isolation against frozen fixtures. No production activation or repository write is implied by a passing score.
- **LOOP execution:** the existing LOOP may consume a bounded, reviewed task. Its schedule is not a prerequisite for the other modes.

## First implementation sequence

### A. Establish a measurable baseline

Create a small, versioned evaluation set covering:
- source-grounded question answering;
- multi-step task decomposition;
- memory retrieval and rejection of stale/contradictory memories;
- uncertainty and abstention when evidence is insufficient;
- prompt-injection resistance for retrieved content;
- reproducibility and resource limits.

Record the dataset digest, evaluator version, baseline scores, and known limitations. Do not use a model's self-rating as the sole evaluator.

### B. Connect memory to research artifacts

Extend the existing bounded history only after defining a typed knowledge record with:
- stable record ID and schema version;
- claim or lesson;
- source URI/commit/run identifier and evidence digest;
- observed-at and freshness/expiry metadata;
- confidence and validation status;
- links to superseding or contradictory records.

Keep raw retrieved text separate from trusted metadata. Retrieval returns evidence, never authority.

### C. Build a provider-neutral intelligence pipeline

Compose the existing task contracts and evaluators behind small interfaces:
`Researcher`, `MemoryStore`, `Reasoner`, and `IndependentEvaluator`.
A pipeline run should emit an immutable report containing inputs, evidence references, candidate answer/plan, evaluation results, and a next-step proposal. It must not mutate source code, approvals, production models, or deployment state.

### D. Add improvement experiments

Use RSI to propose one change at a time. Run the same frozen evaluation suite before and after. Reject regressions in safety or factual support even when another metric improves. Store the complete experiment evidence and keep model activation/manual approval separate.

### E. Operate independently of LOOP

Expose the intelligence pipeline as an explicitly invoked, bounded workflow first. Only after reliability, cost, and usefulness are demonstrated should a separate schedule be considered. Do not create another 15/30-minute loop merely to make the intelligence pipeline appear active.

## Acceptance criteria

The first usable ASDI foundation is complete only when:

- a non-LOOP invocation can produce a source-grounded research/reasoning report;
- the report records provenance and uncertainty;
- memory retrieval is tested for relevance, freshness, contradiction, and prompt injection;
- an independent evaluator runs against a frozen, digest-pinned test set;
- a repeated run is reproducible within documented tolerances;
- a proposed improvement is rejected on safety regression;
- the whole path works without paid APIs, RunPod, Kaggle, or a local model server;
- no code, model, approval, merge, or deployment mutation occurs without its separate authorization.

## Explicit non-goals

- Claiming that the current repository is already superintelligent.
- Adding another scheduler or parallel loop framework.
- Automatically trusting model-generated memories, plans, or code.
- Automatically changing model weights, activating a generation, merging, or deploying.
- Optimizing benchmark scores by changing the held-out evaluation set.

## Immediate next engineering task

Implement the versioned knowledge-record and retrieval contract, with unit tests for provenance, freshness, contradictions, untrusted content, and bounded storage. Then connect it to the existing research/agent runtime and frozen evaluator. This is the highest-leverage first step because durable, trustworthy knowledge is needed by reasoning, research, and self-improvement alike.
