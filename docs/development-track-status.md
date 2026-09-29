# Development Track Status

Last updated: 2026-09-29

This file separates progress tracking for the three active input/development tracks. Status is based on repository state; an item is not marked complete until its implementation and relevant verification are actually confirmed.

## 1. Distributed AI Loop
- Goal: autonomous development cycle with task selection, parallel/safe execution, tests, verification, safety gate, bounded recovery/retry, audit logging, and no automatic merge/deploy.
- Current: **FOUNDATION READY / LIVE RUN PENDING**
- Implemented:
  - `.github/autonomous-loop-tasks.json`
  - `.github/workflows/distributed-autonomous-loop.yml`
  - task continuation after no-change/failure
  - draft PR publication without auto-merge/deploy
- Next:
  1. Execute one real scheduled/manual run.
  2. Verify each task result, tests, safety gate, and artifacts.
  3. Add bounded Recover -> Retry -> Verify -> Resume behavior.
  4. Add hard-stop behavior for unsafe/unknown failures.
  5. Verify Google Sheets audit from an actual run.
- Completion gate: real run + evidence + safe recovery/stop behavior verified.

## 2. Hand-sign / Camera
- Goal: **hand signs act like a mouse**; reliable recognition of multiple signs and practical UI operations.
- Current: **CAMERA SMOKE TEST READY / RECOGNITION PENDING**
- Implemented:
  - `/camera-test`
  - mobile camera start/stop and camera selection
  - no frame upload/storage in smoke-test page
  - browser-level safety tests
- Next:
  1. Add client-side hand landmark/gesture recognition.
  2. Implement baseline gestures: open palm, fist, one/two/three/four/five fingers, point, peace, thumbs up/down, wave.
  3. Add temporal recognition for motion gestures.
  4. Test front/rear camera, distance, angle, lighting, and movement.
  5. Map reliable gestures to mouse-like actions.
- Completion gate: multiple real-device signs correctly recognized and verified; uncertain recognition must not trigger unsafe actions.

## 3. Spoken Language
- Goal: **spoken language acts like a keyboard**; natural sentences, search, questions, and complex AI/PC instructions.
- Current: **DESIGN DEFINED / IMPLEMENTATION PENDING**
- Scope:
  - speech-to-text
  - natural-language intent/command handling
  - text input equivalent for AI/PC workflows
  - clarification when intent is ambiguous
  - safety confirmation for high-impact actions
- Next:
  1. Choose a free/local-first speech recognition path.
  2. Build microphone permission/state handling.
  3. Add Japanese speech-to-text test page/API.
  4. Add natural-language command routing.
  5. Connect spoken commands to the common operation layer.
- Completion gate: natural Japanese spoken instructions are transcribed, understood, and routed without paid API dependency.

## Cross-track integration
- Hand sign = mouse-like fast interaction.
- Spoken language = keyboard-like expressive input.
- Both feed a common operation layer.
- Safety-critical actions remain fail-closed.
- Local Hermes remains outside the distributed loop unless explicitly re-enabled.
