# UHIP Threat Model

## Assets

- User control over the computer
- Camera/microphone privacy
- Application state
- Universal Event integrity
- Recognition audit data

## Trust boundaries

1. Camera/microphone sensors -> local recognition
2. Recognition -> Recognition Gate
3. Recognition Gate -> Universal Event Core
4. Universal Event Core -> application Policy Gate
5. Policy Gate -> actuator

Phase 0 stops at boundary 3 and has no actuator.

## Threats

### False acceptance
A normal gesture must not become an actionable event. Phase 0 measures false-trigger behavior using negative traces and applies a rule-of-three upper bound.

### Ambiguous tracking
Multiple hands, multiple people, unstable tracking, low confidence, or out-of-frame landmarks fail closed.

### Replay/injection
Later network phases must use paired devices, authenticated sessions, monotonic sequence numbers, expiry, and per-device capabilities. Discovery is never authentication.

### Prompt/voice injection
Voice and AI-generated text are untrusted input. They must never bypass the application Policy Gate.

### Approval confusion
Recognition events do not contain application approval hashes. The Policy Gate creates and binds approval to action, target, parameters, and expiry.

### Actuator compromise
The actuator must be isolated from recognition and Policy Gate, revalidate every action, use an allowlist, and stop when the independent Kill Switch/heartbeat fails.

## Phase 0 boundary

No network, no OS automation, no voice, no iPhone, and no persistent raw sensor data.
