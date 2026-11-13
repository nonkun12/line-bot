# GitHub-native state persistence contract

## Minimal persistence model

Use one dedicated state ref for queue and latched Global HOLD. The state ref is
append-only: each state commit has the exact previously observed ref commit as
its parent. Writers must serialize through a single GitHub Actions concurrency
group with `cancel-in-progress: false`, but concurrency is only a secondary
guard, not the transaction guarantee.

## Required write protocol

1. Read the state ref and state document together; missing/malformed state is
   BLOCKED (never initialize to HOLD=false).
2. Validate queue invariants and expected revision.
3. Build a new state with revision incremented exactly once.
4. Create a commit whose parent is the exact observed ref SHA.
5. Update the ref with force=false. If GitHub rejects the non-fast-forward
   update or the ref has moved, discard the candidate and reread/recompute.
6. Never retry by force-pushing or by reusing stale state.
7. Re-read the ref after update and verify the persisted document digest and
   revision before reporting success.

## Concurrency and limitations

GitHub Actions concurrency may coalesce pending runs; it is not a durable task
queue. Intake must remain discoverable in the task source until a serialized
worker has committed a claim. The Git ref fast-forward check is the intended
compare-and-swap boundary. This contract helper only validates write intents;
it does not call GitHub APIs or prove that a caller actually used the required
REST sequence. A real adapter and integration race tests remain required.

## Safety defaults

- Global HOLD initializes true; missing state blocks.
- Only latching HOLD is permitted in the minimal worker path. HOLD release is
  deliberately not implemented here.
- A claim is valid only after its state commit is confirmed by read-after-write.
- One active lease maximum; lease expiry returns a task to queued only through
  a serialized state transition.
- No merge, deploy, patch application, credential mutation, or automatic HOLD
  release is part of this phase.
