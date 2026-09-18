"""Safe dispatch contract for distributed AI domain agents.

This layer only converts a routing decision into an executable task contract.
It performs no model calls, I/O, file mutation, or automatic execution.
"""
from __future__ import annotations

from dataclasses import dataclass

from .agent_router import RouteDecision
from .multi_agent import AgentRole, AgentTask


@dataclass(frozen=True)
class DispatchContract:
    task: AgentTask
    routed_role: AgentRole


def build_dispatch_contract(
    request_id: str,
    instruction: str,
    decision: RouteDecision,
) -> DispatchContract:
    if not request_id.strip():
        raise ValueError("request_id is required")
    if not instruction.strip():
        raise ValueError("instruction is required")

    task = AgentTask(
        task_id=request_id.strip(),
        role=decision.role,
        instruction=instruction.strip(),
        resources=frozenset({"request:" + request_id.strip()}),
    )
    return DispatchContract(task=task, routed_role=decision.role)
