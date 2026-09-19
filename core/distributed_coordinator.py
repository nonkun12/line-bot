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
from .specialist_gate import SpecialistGateError, assert_specialist_approved


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

    def dispatch(
        self,
        request_id: str,
        instruction: str,
        *,
        expected_role: AgentRole | None = None,
    ) -> CoordinatorReport:
        """Dispatch exactly one task to exactly one specialist role.

        ``expected_role`` is passed by callers that already selected a
        specialist (e.g. request_path's explicit handlers). In that case the
        keyword router is NOT consulted, so the role that is capability-checked
        is by construction the role that executes. Without it the router picks
        the role. Either way the FINAL role is gated before any contract is
        built or executor is invoked (fail-closed).
        """
        if expected_role is None:
            decision = route_instruction(instruction)
        else:
            if not isinstance(expected_role, AgentRole):
                raise TypeError("expected_role must be an AgentRole")
            decision = RouteDecision(expected_role, "explicit specialist")

        assert_specialist_approved(decision.role)

        contract = build_dispatch_contract(request_id, instruction, decision)
        if contract.task.role is not decision.role or contract.routed_role is not decision.role:
            raise SpecialistGateError("dispatch contract role diverged from approved role")
        runtime = self._runtime.run((contract.task,))
        return CoordinatorReport(
            request_id=request_id.strip(),
            decision=decision,
            contract=contract,
            runtime=runtime,
        )
