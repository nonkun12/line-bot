"""Safe coordinator for routing and executing one distributed AI request.

The coordinator keeps routing, contract creation, and bounded runtime execution
separate. It never creates an executor implicitly and therefore fails closed when
a domain has not been wired yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .agent_router import RouteDecision, route_instruction
from .distributed_dispatch import DispatchContract, build_dispatch_contract
from .multi_agent import AgentResult, AgentRole, AgentTask
from .agent_runtime import MultiAgentRuntime, RuntimeExecutor, RuntimeReport


@dataclass(frozen=True)
class CoordinatorReport:
    request_id: str
    decision: RouteDecision
    contract: DispatchContract
    runtime: RuntimeReport

    @property
    def success(self) -> bool:
        return self.runtime.success


class DistributedAgentCoordinator:
    """Route one request and execute it through the existing bounded runtime."""

    def __init__(
        self,
        executors: Mapping[AgentRole, RuntimeExecutor],
        *,
        max_rounds: int = 1,
    ) -> None:
        self._executors = dict(executors)
        self._runtime = MultiAgentRuntime(
            self._executors,
            max_workers=1,
            max_rounds=max_rounds,
        )

    def dispatch(self, request_id: str, instruction: str) -> CoordinatorReport:
        decision = route_instruction(instruction)
        contract = build_dispatch_contract(request_id, instruction, decision)
        runtime = self._runtime.run((contract.task,))
        return CoordinatorReport(
            request_id=request_id.strip(),
            decision=decision,
            contract=contract,
            runtime=runtime,
        )
