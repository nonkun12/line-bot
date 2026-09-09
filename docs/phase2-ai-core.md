# AI Core Phase 2

## Goal
Move execution of migrated agents from the fixed LangGraph node table to a Core `AgentRegistry`-driven graph, without changing the public `/internal/ask` contract during the migration.

## Current scope
- `AgentRegistry` supplies executable agent nodes to the Core-native LangGraph runtime.
- Arbitrary registered agent names are converted into safe, stable LangGraph node names.
- Explicit `next_agent` selection uses the registry when the agent is enabled.
- Generic requests use registry priority ordering.
- Unknown or unavailable agents use the Core fallback.
- Real migrated Notes execution is covered through the registry-backed graph factory.

## Safety boundary
The production `graph/graph.py` remains unchanged on this branch. Integration into the production request path is a separate step after this standalone Core graph passes regression and review.

## Next integration step
Replace one legacy route at a time with the Core graph while keeping the existing legacy graph as the compatibility path until each route has equivalent end-to-end coverage.
