# RSI Executor foundation (Stages 1-6)

This is a separate RSI experiment path. It is not the generic distributed-loop
worker and does not treat ordinary queue completion as self-improvement.

## Implemented foundation

1. **Typed RSI executor** — `core/rsi_executor.py` defines typed observations,
   diagnoses, hypotheses, experiment plans, approvals, results, and evaluations.
2. **Persistent evidence** — `EvidenceLedger` stores append-only SQLite records
   with a SHA-256 hash chain and update/delete-denying triggers.
3. **Diagnosis and hypotheses** — deterministic bounded diagnosis groups
   evidence-backed FAIL/REGRESSED observations. It labels causes unverified;
   it does not claim an LLM has discovered root cause.
4. **Independent evaluation** — the evaluator identity must differ from the
   executor, and a caller-supplied signature verifier must accept the report.
5. **Next-experiment selection** — deterministic, bounded selection ranks
   proposals by information value, cost, and risk.
6. **Safety tests** — tests cover HOLD, FREE-only, unknown budget, disabled
   execution, approval binding, evaluator separation, digest validation,
   duplicate evidence, and append-only ledger behavior.

## Local-model advisory integration

`core/rsi_local_advisor.py` reuses Stage 132's `LocalModelClient` and provides
`build_loopback_rsi_advisor()` pinned to `http://127.0.0.1:11434` with bounded
output. It supplies one alternative hypothesis and falsification test as
append-only proposal evidence. The model output is strict-schema validated and
cannot authorize execution, certify evaluation, grant approval, or activate a
model. This is advisory support; deterministic executor decisions remain the
source of the experiment plan and selection.

The existing Stage 160 gate governs the separate Stage 159 evolutionary merge
proposal contract. It is not silently treated as an adapter for generic RSI
plans: those types and authority scopes differ and require an explicit reviewed
bridge before any evolutionary merge experiment can be dispatched.

## Authority boundary

- Global HOLD, non-FREE paths, paid fallback, unknown budget, and insufficient
  budget fail closed.
- Planning is proposal-only. Execution additionally requires
  `execution_enabled=true`, a verified approval bound to the exact plan digest,
  and an injected local runner.
- The runner is an adapter; this module does not start a model or subprocess.
- An independent evaluator adapter and signature verifier are mandatory.
- No weight/tensor mutation, model merge, generation advancement, registry
  activation, production switch, auto-merge, or deployment is implemented.
- No scheduler or background worker is enabled by this change.

## Validation status

GitHub Actions validation for commit `58b6c14` completed successfully:
Python syntax scan, the full Pytest workflow, and the repository's free
deterministic-loop workflow all reported success. The deterministic-loop
workflow had an empty task queue and executed no RSI task. The AI Code Review
workflow also completed, but that workflow only checks out the repository and
prints the diff; it is not a substantive independent code review.

Live Ollama execution, a trusted budget source, a concrete experiment runner,
a signed independent-evaluator adapter, and runtime control-plane wiring are
not claimed. The generic RSI executor remains execution-off by default. The
next integration task is to provide verified local experiment/evaluation
adapters and a trusted read-only control/budget provider, then run them only in
an isolated local environment after explicit approval.


## End-to-end proposal cycle

`core/rsi_cycle.py` now orchestrates one bounded proposal cycle:
observation -> deterministic diagnosis -> falsifiable hypothesis -> optional
loopback local-model advisory note -> digest-bound plan -> deterministic
selection. It returns an explicit `PROPOSAL_READY` or
`NO_IMPROVEMENT_TARGET` state. It never invokes a runner, grants approval,
certifies evaluation, or activates a model. Advisor failure stops the cycle
rather than being interpreted as a pass.

Planning now checks the known remaining FREE budget against the requested
experiment cost before creating plans; selection excludes plans that are no
longer affordable. The budget value is still supplied by an injected provider,
not claimed to be a trusted live account-wide quota measurement.


## Local execution and independent evaluation adapters

- `core/rsi_local_runner.py` provides an allowlisted, inference-only local benchmark runner. It accepts only a fixed 1..4-case suite, checks the exact candidate/protocol digests and configured Ollama model identity, uses the Stage 132 loopback client, and stores raw outputs plus expected answers in the append-only evidence ledger. It has no shell, arbitrary file, remote network, model-weight, or activation interface.
- `core/rsi_local_evaluator.py` provides a distinct local evaluator identity/client. It re-reads and verifies immutable raw benchmark evidence, recomputes every exact-match result and aggregate metric, checks the result digest, then fixes IMPROVED/NO_CHANGE/REGRESSED deterministically against an injected frozen-baseline score. The local evaluator model supplies rationale only; it cannot change the decision. An injected evaluator-held signing callback signs the result, and the executor verifies it independently. No key material is generated or stored by this module.
- `core/rsi_control.py` accepts only typed, signed, freshness-bounded control snapshots from an injected trusted source. Signature verification is mandatory; stale, expired, malformed, replayed, or unknown-budget snapshots fail closed. It does not treat GitHub Actions minutes, environment variables, or dashboard text as an account-wide FREE budget.
- `tests/test_rsi_integration.py` covers a full proposal -> exact human approval -> local inference run -> separately signed evaluation path, plus execution-disabled blocking before the runner is invoked.

## Deployment prerequisites still not met

These adapters are testable contracts, not a live deployment. The trusted control snapshot issuer, evaluator-held signing key/public-key verifier, local Ollama process, immutable candidate artifact registry, and runtime operator/scheduler are not wired into production. The current local benchmark tests prompt-following on an existing local model; it does not mutate or merge weights and does not establish evolutionary model-merging capability. No scheduler is enabled. Global HOLD and execution OFF remain the required default until those external trust roots are provisioned and reviewed.


## Bounded proposal supervisor

`core/rsi_supervisor.py` adds an explicitly invoked synchronous batch/tick
interface with a hard 1..4 cycle limit. Each cycle re-enters the executor's
control gate. It stops when no improvement target exists and never invokes a
runner, timer, daemon, or scheduler. This prepares a bounded control surface
for later scheduling review without starting continuous execution.


## Local LFM3 connectivity smoke check (2026-11-16)

The user manually verified the local `lfm3:1.7b-qad-q4_0` Ollama
`/api/chat` endpoint on the Mac using `think=false`, `temperature=0`,
and the same three fixed prompts as the local runner. All three expected
tokens were returned exactly (3/3). This confirms local model/API prompt
execution only; it is not a runner invocation, append-only ledger record,
independent evaluation, or evidence of improvement over a frozen baseline.

The Stage 132 client now supports an explicit optional `think` setting, and
`build_loopback_rsi_runner()` pins the endpoint to loopback, verifies the exact
configured Ollama tag digest against the approved candidate digest before
execution, sets `think=false`, and caps output at 128 tokens. The runner and evaluator both
require exact stripped-output equality; a response that merely contains the
expected token is scored as a mismatch. The latest CI run validates this
hardening separately from the earlier full-suite baseline run.


## Signed frozen baseline contract

`core/rsi_baseline.py` adds a signed `FrozenBaseline` record binding the
baseline score to an immutable baseline model digest, the exact benchmark
protocol digest, sample count, baseline identifier, and sealing timestamp.
The independent evaluator now requires this record, verifies its external
signature and freshness, and rejects a plan whose baseline digest or protocol
does not match. A caller-supplied floating-point score is no longer sufficient
to declare IMPROVED/NO_CHANGE/REGRESSED. Signing keys and trusted baseline
measurement remain external prerequisites; the included tests use test-only
signatures and do not constitute a production trust root.


## P0 hardening: evidence provenance and monotonic control state

- Observation evidence now requires a ledger event of the explicit
  `trusted_observation_evidence` type. The event digest must match the
  observation reference, its signed payload must exactly match the observation,
  and its experiment, candidate, protocol, and result digests must match the
  typed reference. The producer identity/signature is checked by an injected
  independent verifier.
- The complete hash chain, source-event lookup, signature verification, and
  observation append run under one SQLite `BEGIN IMMEDIATE` transaction.
  Missing, forbidden, mismatched, unsigned, forged, or tampered evidence is
  rejected before an observation enters the ledger.
- The local benchmark runner now requires an injected producer signer. Its
  signature covers the experiment, candidate, protocol, recomputed result
  digest, and raw observations. The independent evaluator verifies that
  signature and all plan/result bindings before recomputing the score.
- The independent evaluator also requires the signed frozen baseline's
  `sample_count` to equal the number of independently verified challenger
  observations. A mismatch is rejected before the evaluator model is called
  for rationale, preventing scores from differently sized benchmark samples
  from being compared as if they were equivalent.
- Signed control snapshots now require a generation number covered by the
  signature. Generation and issued-at values are checked against the durable
  append-only ledger, not process memory. Replayed nonces, generation
  rollback/equivocation, issue-time rollback, invalid legacy history, and
  ledger corruption fail closed. The history check and append are serialized
  in one `BEGIN IMMEDIATE` transaction, including across provider restarts.
- A transition from Global HOLD to HOLD-clear requires a separate
  `HumanControlReleaseApproval` signed by an independently injected verifier,
  bound to the previous HOLD generation and exact release snapshot digest,
  generation, nonce, approver, and validity window. Experiment approval cannot
  release Global HOLD.

These are secure interfaces, not a claim that production trust roots are
provisioned. The observation producer signer/verifier, benchmark signer,
trusted control snapshot issuer, control-release approver/verifier, and FREE
budget source remain external dependencies. No generation advancement,
scheduler activation, merge, deployment, or model activation is performed.

## Orchestra AI and REA integration contract (design; not yet activated)

The intended orchestration hierarchy is:

1. **Orchestra AI / Orca** is the coordination layer. It decomposes approved goals
   into bounded work items, assigns them to eligible workers, deduplicates tasks,
   tracks dependencies, and consolidates evidence-backed status across the
   distributed streams. It may propose queue replenishment, but queue creation
   and dispatch remain subject to the existing task-approval and control gates.
2. **RSA / RSI** performs evidence-backed diagnosis, hypothesis generation,
   bounded experiment planning, and (only after separate approval) isolated
   experiment execution and evaluation.
3. **REA (Creator-Critic Runtime)** provides a separate proposal-quality loop:
   Creator drafts a candidate change; Critic independently checks objective
   alignment, safety constraints, test evidence, regression risk, and whether
   the proposed change is falsifiable. Creator and Critic identities and
   evidence must remain distinguishable. A Creator cannot approve its own
   proposal, and a Critic pass is not execution or merge authority.
4. **Control Tower** remains the authority boundary. It validates task identity,
   exact HEAD/patch digests, evidence provenance, budget state, approvals, and
   HOLD status immediately before any privileged action. Orchestra, RSA, REA,
   worker agents, and dashboards cannot override it.

### Required hand-off envelope

Every cross-agent hand-off must carry a stable task ID, parent/child lineage,
repository and exact commit SHA, candidate/patch digest where applicable,
objective and acceptance criteria, evidence references, assigned role, and
explicit allowed actions. The receiver must reject missing or mismatched
identity/digest fields. Results are append-only evidence; summaries or model
text alone are not proof of execution or success.

### Fail-closed orchestration rules

- Missing Orchestra worker, REA Critic, evidence, budget, or required approval
  results in BLOCKED/HOLD, not an inferred pass.
- Queue replenishment may create proposals only; it must not self-authorize
  execution. Empty queues are reported separately from successful work.
- Parallel workers receive disjoint bounded tasks or explicit dependency locks;
  conflicting writes and duplicate execution are rejected.
- Critic review must be independent of the Creator and must bind to the exact
  candidate digest and test evidence it reviewed.
- A passing REA review does not release Global HOLD, grant human approval,
  enable execution, merge a PR, deploy, or activate a model.
- Orchestra may coordinate status and request work, but may not change safety
  policy, credentials, trust roots, scheduler state, or deployment permissions.
- Every run records PASS, FAIL, NO_CHANGE, or BLOCKED with evidence references;
  scheduled ticks and empty-queue checks are not counted as completed RSI work.

### Implementation status

The full multi-stream Orchestra runtime, production REA provider wiring,
cross-agent dispatch, and dashboard integration remain future work. The
bounded proposal/review hand-off below is implemented as a non-dispatching
adapter only. The existing RSI foundation remains execution-off by default;
no scheduler, continuous loop, merge, deployment, or model activation is enabled.

## Bounded Orchestra -> RSI -> REA proposal/review hand-off

`core/rsi_orchestra.py` now coordinates the existing bounded RSI proposal
supervisor with separate injected Creator and Critic agents. For each selected
plan it creates a hand-off envelope bound to repository, exact HEAD SHA,
experiment ID, plan digest, Creator candidate digest, and evidence digest.
A mandatory independent evidence-verifier callback must validate the evidence
against that exact envelope before the Critic is called. Creator and Critic
must use distinct injected callable objects; a shared callable is rejected.

The Critic receives the immutable hand-off bindings together with measured
evidence. A review is PASS only when the Critic's evidence is unchanged and
its deterministic evidence thresholds pass. Missing or invalid evidence,
adapter errors, and binding mismatches produce BLOCKED; a failed review remains
REVIEW_REQUIRED. The result explicitly keeps dispatch, execution, scheduling,
patch, merge/deploy, HOLD-clear, and model activation authority false.

This is a proposal/review integration only. The evidence verifier must be
wired to a real trusted test/evidence source before operational use. The
Orchestra module does not create queue items, dispatch workers, mutate files,
run experiments, or start a continuous loop. Existing Control Tower and
human-approval gates remain mandatory for any later privileged action.

Each REA review, including BLOCKED outcomes, is also recorded as a digest-only
`orchestra_rea_review` event in the RSI append-only ledger. The adapter checks
ledger integrity before and after append; persistence failure downgrades the
review to BLOCKED. The event stores identity/digest bindings, decision and
score, and a digest of Critic feedback rather than raw model text.

## Control Tower status bridge

`scripts/rsi_orchestra_control_tower_adapter.py` converts the typed Orchestra
batch into a sanitized Control Tower status row only after re-reading each
review event from the append-only ledger and matching repository, exact HEAD,
plan/candidate/evidence digests, status, and authority flags. It maps a complete
REA pass to `PASS / REQUEST_HUMAN_REVIEW`, a Critic failure to
`FAIL / REPORT_REVIEW_REQUIRED`, and missing or inconsistent evidence to
`BLOCKED / HOLD_AND_REPORT`. Every result sets `allow_continue=false` and
keeps execution, patch, HOLD-clear, merge/deploy, scheduling, and model
activation disabled. This is a status-ingestion adapter; it does not yet wire
the result into the live Orca dashboard or distributed worker dispatcher.



## Local REA model wiring and Orca status projection

`core/rsi_rea_local.py` provides a concrete loopback-only Creator/Critic factory.
It binds two distinct Ollama model identities to separate role clients at
`127.0.0.1:11434`; it does not configure a remote provider or tool execution.
Callers must still supply the independently trusted evidence verifier required
by `OrchestraRSIBatch`, and model output remains proposal/review material only.

The Orca snapshot sanitizer and publisher accept an optional `rsi_review`
summary. The summary is allowlisted, bounded, strips raw feedback, and rejects
any true execution, patch, continuation, HOLD-clear, merge/deploy, scheduler,
or model-activation authority flag. `/api/dashboard/orca` exposes only that
sanitized summary. It is a status projection, not a dispatch integration.

`DistributedTaskScheduler` now rejects duplicate task IDs within one submitted
plan before invoking any executor. Existing resource/dependency batching remains
in place. This is an in-run duplicate guard; it does not claim cross-run durable
idempotency for arbitrary external dispatchers.

## Remaining live integration boundaries

- Real Creator/Critic model calls require the configured local Ollama service and
  verified model digests at deployment time.
- A trusted evidence producer/verifier and signer remain externally injected.
- The status summary must be supplied by a trusted, already-verified caller; the
  dashboard HMAC authenticates the publisher but does not independently prove
  the underlying REA review.
- The Orca worker/queue dispatcher is not automatically connected to this
  adapter. No live scheduling, task execution, HOLD release, or activation is
  performed by these changes.