# Parallel Loop Architecture (bounded foundation)

This is the first concurrency slice for the distributed AI Loop.

## Invariants

- Loop IDs are explicitly registered; loops cannot self-create.
- Concurrency is bounded by a fixed dispatcher limit.
- Tasks declare resources; tasks sharing a resource are serialized.
- A latched stop prevents new handler execution.
- Per-loop iteration limits are explicit.
- This module does not merge, deploy, grant permissions, or bypass Safety Gate.
- Production runtime integration is a separate guarded step.

## Intended execution boundary

Task Queue -> Parallel Dispatcher -> isolated worker/workspace -> TEST -> Verification -> Safety Gate -> Integration

The dispatcher is deliberately provider-neutral. It can later wrap the existing
Management/Development/TEST/Verification runtime without replacing its safety
controls.
