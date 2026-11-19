# Stage 131: concrete AI Factory adapter integration

Stage 131 connects the existing Stage 122, Stage 123, Stage 121, and Stage
126-130 interfaces without adding a model provider or changing production
permissions.

## Flow

1. A Stage 122 `CapabilityGap` is mapped to the orchestrator's validated
   `CapabilityGapRequest`.
2. The Stage 123 evidence runner asks four separately injected role producers
   for DESIGN, BUILD, TEST, and REVIEW evidence. The existing immutable
   collaboration pipeline validates role identity and stage order.
3. Only a COMPLETE Stage 123 packet is passed to the Stage 121 factory.
4. `Stage121FactoryAdapter` binds the exact Stage 122 gap to the existing
   `CapabilityGapArchitect` and delegates to `AgentFactory.create_candidate`.
5. The Stage 126-130 orchestrator verifies Stage 121 sandbox and review
   evidence and returns an inert candidate awaiting human approval.

## Explicitly not connected

- No LLM/local model provider is invoked. Role producers are injected adapters;
  they must be connected to an approved provider separately.
- No generated code is executed and no files are written.
- No catalog registration or runtime activation occurs automatically.
- No LINE/Orca approval source, persistent catalog, scheduler, kill-switch
  source, or durable LOOP state is modified.
- No HOLD release, permission escalation, merge, or deployment occurs.

## Verification

Tests cover successful interface wiring, incomplete/failed test evidence,
rejected review, role spoofing, missing role producers, and no auto-registration.
