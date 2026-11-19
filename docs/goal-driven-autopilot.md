# Durable goal-controller foundation

Adds a SQLite-backed, revisioned state store around the pure goal policy engine. A claim atomically persists IN_PROGRESS before any external work. A second worker sees the in-flight task and HOLDs; restart preserves the claim and requires reconciliation instead of silent retry. Completion requires task-bound verified evidence.

## Boundary

This change does not launch the guarded runtime, dispatch Actions, mutate the existing runtime queue, create Issues or PRs, merge, or deploy. It is a durable lifecycle primitive, not yet the production autonomous loop. A separate reviewed integration must map authorized goal tasks to the guarded runner and independently verify real test/run evidence under the existing serialized workflow owner.

The schedule remains best-effort, not a 24/7 uptime guarantee. Local-only models cannot run while the Mac is off. AUTO_APPLY_PATCH=false and AUTO_DEPLOY=false remain unchanged.
