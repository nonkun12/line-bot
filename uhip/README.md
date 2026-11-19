# Universal Human Input Platform (UHIP)

Phase 0 establishes a local, camera-only recognition foundation.

## Scope

Phase 0 intentionally does not perform network communication, OS actions, voice input, iPhone integration, or application control.

Pipeline:

camera -> local landmarks -> classifier -> Recognition Gate -> Universal Event draft -> local statistics/replay

## Safety invariants

- Recognition failure never produces an actionable event.
- Low confidence, unstable tracking, out-of-frame input, and multiple hands/people fail closed.
- No recognition result can directly execute an OS action.
- No audio, image, landmark, or transcript is retained by default.
- Approval state belongs to the application Policy Gate, not the recognition layer.
- Deterministic replay is a required validation path.

## Planned phases

1. Phase 0: camera recognition statistics and deterministic replay
2. Threat model, privacy, licensing and event schema hardening
3. Pairing/authenticated Universal Event transport
4. iPhone and voice adapters
5. AI Secretary / browser / media / presentation application adapters
