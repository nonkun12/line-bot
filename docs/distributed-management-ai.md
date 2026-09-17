# Distributed Management AI

## Target architecture

The system separates management from specialist execution:

Management AI receives the user request, selects a primary route, decomposes the request into bounded specialist tasks, and decides which tasks can run independently.

Each specialist AI receives only its assigned task and declared resources. Independent tasks may run in parallel only when the caller explicitly enables isolation.

Every specialist returns a result packet. The management layer collects those results and can use the bounded message bus for the next coordination round.

## Current foundation

- `core/management_ai.py`: planning, validation, dispatch, and result collection.
- `core/distributed_scheduler.py`: dependency/resource-aware scheduling.
- `core/agent_communication.py`: bounded agent-to-agent message envelopes and mailboxes.
- `core/multi_agent.py`: specialist role contracts.

Model output is untrusted planning data. It is validated before execution and cannot grant permissions, invoke tools, mutate repositories, or deploy systems.

## Future communication model

The intended progression is:

1. Management AI -> specialist A/B/C task assignment.
2. Specialists execute independently and return results.
3. Management AI compares results and issues the next bounded round.
4. Specialist A -> specialist B messages become possible through the message bus.
5. Direct collaboration remains constrained by explicit routes, safety constraints, and resource ownership.
6. Repository-changing agents remain behind isolated worktrees and the existing review/integration gates.

This branch does not add autonomous production mutation or automatic merging.
