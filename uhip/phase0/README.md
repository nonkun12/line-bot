# UHIP Phase 0 Safe Core

This package is the local-only safety core for Phase 0.

Pipeline:

camera adapter -> local observation -> Recognition Gate -> Universal Event draft -> replay

The package deliberately does **not**:

- perform network communication;
- execute OS actions;
- invoke LINE, browser, shell, or application adapters;
- retain camera/audio data;
- auto-authorize an application action.

The Recognition Gate fails closed when:

- more than one hand is present;
- the hand is out of frame;
- raw or calibrated confidence is below policy;
- tracking is not stable;
- the gesture is outside the allowlist;
- the source is not the Phase 0 local Mac camera.

Replay consumes bounded JSONL observations and produces deterministic pass/fail results.

The actual camera/landmark adapter remains a separate boundary so that model/library choices cannot bypass the gate.
