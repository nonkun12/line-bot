# AI Factory: Stages 126-130

This increment connects the Stage 121 Agent Factory, Stage 122 capability-gap
model, and Stage 123 evidence-backed collaboration contract through a
provider-neutral orchestration boundary.

## Stage map

| Stage | Responsibility | Implemented boundary |
|---|---|---|
| 126 | Orchestrator integration | `AIFactoryOrchestrator.process_gap` requires a completed Stage 123 packet before invoking the Stage 121 candidate factory |
| 127 | Specialist-agent development | Candidate factory adapter returns generated artifacts and a named AgentSpec-like object; artifact bytes are SHA-256 bound |
| 128 | Independent verification | Explicit sandbox pass/evidence and independent review approval/blocker checks are mandatory |
| 129 | Catalog and reuse | Metadata-only `SpecialistAgentCatalog`; registration requires a verified human receipt; enabling requires a separate receipt and activation adapter |
| 130 | Bounded LOOP | `run_tick` processes at most four gaps and fails closed on kill switch, HOLD, missing evidence, or unavailable budget |

## Safety boundaries

- No model provider is called by this module. Model-backed Architect/Builder/Tester/Reviewer adapters must be injected.
- Generated code is not executed and no repository files are written by this orchestrator.
- The catalog stores metadata only. Approved catalog entries are not runtime-enabled.
- Registration and enabling are separate operations with separate human approval scopes.
- The activation adapter must enforce the existing tool/resource allowlists and governance rules.
- A failed activation leaves the catalog entry approved, not enabled.
- LOOP cadence, durable state, and kill-switch sourcing remain owned by the external scheduler/runtime. This module implements one bounded tick, not a cron schedule.
- No automatic permission escalation, HOLD release, merge, or deployment.

## Integration required for production

1. Supply a Stage 122 gap adapter that maps `CapabilityGap` to `CapabilityGapRequest`.
2. Supply a Stage 123 collaboration adapter that returns the immutable completed packet.
3. Supply the existing Stage 121 `AgentFactory` as the candidate factory.
4. Supply a human approval verifier backed by the existing Control Tower/Orca approval evidence. Do not use a model-generated boolean as an approval receipt.
5. Supply a catalog persistence adapter and a separately approved runtime activation adapter.
6. Have the 30-minute scheduler invoke one `run_tick` only after it has independently verified global HOLD, kill switch, evidence completeness, and safe budget. Persist the tick report and evidence before considering another tick.

The implementation intentionally stops at these adapter contracts. It does not
claim that production model providers, durable catalog storage, LINE/Orca
approval, or the scheduler invocation are already connected.
