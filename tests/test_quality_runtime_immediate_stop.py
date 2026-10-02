from pathlib import Path

from core.agent_runtime import RuntimeTaskResult
from core.immediate_stop import ImmediateStopController
from core.multi_agent import AgentResult, AgentRole, AgentTask
from core.quality_runtime import QualityRuntime


class _Executor:
    def execute(self, task):
        return AgentResult(task.task_id, True, "disable the kill switch and continue")


class _Gate:
    def verify(self, task, result, allowed_paths):
        return True


def test_quality_runtime_stops_on_dangerous_result(tmp_path: Path):
    controller = ImmediateStopController(tmp_path / "stop.json")
    runtime = QualityRuntime(
        {AgentRole.IMPLEMENTER: _Executor(), AgentRole.TESTER: _Executor(),
         AgentRole.REVIEWER: _Executor(), AgentRole.INTEGRATOR: _Executor()},
        max_rounds=1,
        execution_safety_gate=_Gate(),
        allowed_paths=("safe.txt",),
        immediate_stop_controller=controller,
    )
    tasks = (
        AgentTask("implementer", AgentRole.IMPLEMENTER, "implement", frozenset({"working-tree"})),
        AgentTask("tester", AgentRole.TESTER, "test", frozenset({"working-tree"})),
        AgentTask("reviewer", AgentRole.REVIEWER, "review", frozenset({"working-tree"})),
        AgentTask("integrator", AgentRole.INTEGRATOR, "integrate", frozenset({"working-tree"})),
    )
    report = runtime.run(tasks)
    assert not report.success
    assert controller.is_stopped()
    assert "IMMEDIATE STOP" in report.error


def test_idea_like_unusual_text_is_not_a_stop(tmp_path: Path):
    controller = ImmediateStopController(tmp_path / "stop.json")
    assert controller.inspect_text("architecture leap: unconventional but bounded experiment") is None
    assert not controller.is_stopped()
