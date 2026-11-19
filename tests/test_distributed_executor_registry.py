"""Tests for the distributed AI executor registry."""

import pytest

from core.distributed_executor_registry import DistributedExecutorRegistry
from core.multi_agent import AgentResult, AgentRole


class FakeExecutor:
    def execute(self, task):
        return AgentResult(task_id=task.task_id, success=True, summary="ok")


def test_registry_builds_explicit_mapping():
    executor = FakeExecutor()
    registry = DistributedExecutorRegistry()

    registry.register(AgentRole.VOICE, executor)

    mapping = registry.build()
    assert mapping[AgentRole.VOICE] is executor
    assert registry.has(AgentRole.VOICE)


def test_registry_does_not_mutate_from_built_mapping():
    registry = DistributedExecutorRegistry()
    registry.register(AgentRole.NEWS, FakeExecutor())

    mapping = registry.build()

    with pytest.raises(TypeError):
        mapping[AgentRole.STOCKS] = FakeExecutor()


def test_registry_rejects_duplicate_role():
    registry = DistributedExecutorRegistry()
    registry.register(AgentRole.STOCKS, FakeExecutor())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(AgentRole.STOCKS, FakeExecutor())


def test_registry_rejects_invalid_registration():
    registry = DistributedExecutorRegistry()

    with pytest.raises(TypeError):
        registry.register("voice", FakeExecutor())

    with pytest.raises(ValueError):
        registry.register(AgentRole.VOICE, None)


def test_registry_register_many_preserves_fail_closed_behavior():
    registry = DistributedExecutorRegistry()
    registry.register_many({
        AgentRole.ENGLISH: FakeExecutor(),
        AgentRole.VIDEO: FakeExecutor(),
    })

    mapping = registry.build()
    assert set(mapping) == {AgentRole.ENGLISH, AgentRole.VIDEO}
    assert AgentRole.STOCKS not in mapping
