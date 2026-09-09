# AI Core Phase 2

Follow-up work after PR #20. Keep this phase separate from the regression-sensitive Phase 1 migration.

## Scope
- Replace the fixed production LangGraph agent node/edge registration with registry-driven registration.
- Make Core Agent execution (`Agent.handle`) the production execution path rather than only a migration bridge.
- Remove remaining duplicated route/node tables from the production graph.
- Preserve legacy route behavior and terminal/fallback behavior during migration.
- Add end-to-end tests covering `/callback`, `/internal/ask`, `/api/ask`, and registry-backed execution.
- Add runtime coverage for agent enable/disable and deterministic priority resolution.

## Constraints
- Do not merge or deploy automatically.
- Preserve existing regression coverage before changing production graph topology.
- Keep external MCP/API calls mocked in CI-level integration tests.
