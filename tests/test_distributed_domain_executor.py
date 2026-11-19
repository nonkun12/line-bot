"""Tests for explicit distributed domain handler adapters."""

import pytest

from core.distributed_domain_executor import HandlerExecutor, build_domain_executor
from core.multi_agent import AgentResult, AgentRole, AgentTask


def task(role=AgentRole.VOICE):
    return AgentTask("req-1", role, "do it", frozenset({"request:req-1"}))


def test_handler_executor_adapts_string_result():
    executor = HandlerExecutor(lambda t: "voice handled")

    result = executor.execute(task())

    assert result == AgentResult("req-1", True, "voice handled")


def test_handler_executor_accepts_matching_agent_result():
    executor = HandlerExecutor(
        lambda t: AgentResult(t.task_id, True, "structured")
    )

    assert executor.execute(task()).summary == "structured"


def test_handler_executor_rejects_mismatched_task_id():
    executor = HandlerExecutor(lambda t: AgentResult("other", True, "bad"))

    with pytest.raises(ValueError, match="task_id"):
        executor.execute(task())


def test_handler_executor_rejects_invalid_result():
    executor = HandlerExecutor(lambda t: 123)

    with pytest.raises(TypeError, match="AgentResult or str"):
        executor.execute(task())


def test_build_domain_executor_requires_explicit_role_and_handler():
    role, executor = build_domain_executor(AgentRole.STOCKS, lambda t: "stocks")

    assert role is AgentRole.STOCKS
    assert executor.execute(task(AgentRole.STOCKS)).success


def test_build_domain_executor_rejects_invalid_inputs():
    with pytest.raises(TypeError):
        build_domain_executor("voice", lambda t: "bad")
    with pytest.raises(TypeError):
        build_domain_executor(AgentRole.VOICE, None)
