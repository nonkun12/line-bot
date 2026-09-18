"""Tests for the distributed AI coordinator."""

from core.agent_router import route_instruction
from core.distributed_coordinator import DistributedAgentCoordinator
from core.multi_agent import AgentResult, AgentRole


class FakeExecutor:
    def __init__(self, success: bool = True) -> None:
        self.calls = []
        self.success = success

    def execute(self, task):
        self.calls.append(task)
        return AgentResult(
            task_id=task.task_id,
            success=self.success,
            summary="executed" if self.success else "failed",
        )


def test_coordinator_routes_and_executes_through_runtime():
    executor = FakeExecutor()
    coordinator = DistributedAgentCoordinator({AgentRole.VOICE: executor})

    report = coordinator.dispatch("req-1", "AIスピーカーで話して")

    assert report.success
    assert report.decision.role is AgentRole.VOICE
    assert report.contract.task.task_id == "req-1"
    assert executor.calls[0] == report.contract.task


def test_coordinator_fails_closed_when_role_is_unregistered():
    coordinator = DistributedAgentCoordinator({})

    report = coordinator.dispatch("req-2", "株価を調べて")

    assert not report.success
    assert report.decision.role is AgentRole.STOCKS
    assert report.runtime.failed_task_id == "req-2"
    assert "missing executor" in (report.runtime.error or "")


def test_coordinator_preserves_request_scope():
    executor = FakeExecutor()
    coordinator = DistributedAgentCoordinator({AgentRole.ENGLISH: executor})

    report = coordinator.dispatch("req-3", "英語を翻訳して")

    assert report.contract.task.resources == frozenset({"request:req-3"})


def test_coordinator_propagates_executor_failure_without_retrying():
    executor = FakeExecutor(success=False)
    coordinator = DistributedAgentCoordinator({AgentRole.NEWS: executor})

    report = coordinator.dispatch("req-4", "AI NEWSを調べて")

    assert not report.success
    assert report.runtime.failed_task_id == "req-4"
    assert len(executor.calls) == 1
