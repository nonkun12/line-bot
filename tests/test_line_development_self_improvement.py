from types import SimpleNamespace

from core.agent_runtime import RuntimeReport
from core.multi_agent import AgentRole


def test_observe_self_improvement_receives_real_runtime_report(monkeypatch, tmp_path):
    from core import line_development_runtime as runtime

    calls = {}

    class FakeTower:
        pass

    def fake_cycle(report, history_path, *, target_paths, control_tower):
        calls["report"] = report
        calls["history_path"] = history_path
        calls["target_paths"] = target_paths
        calls["control_tower"] = control_tower
        return SimpleNamespace(
            new_signals=("signal",),
            analysis=SimpleNamespace(recurring_patterns=("pattern",)),
            proposals=(),
            approved_proposals=(),
        )

    monkeypatch.setenv("SELF_IMPROVEMENT_CREATOR_CRITIC", "false")
    monkeypatch.setenv("SELF_IMPROVEMENT_HISTORY_PATH", str(tmp_path / "history.jsonl"))
    monkeypatch.setattr(runtime, "ControlTower", lambda **kwargs: FakeTower())
    monkeypatch.setattr(runtime, "run_self_improvement_cycle", fake_cycle)

    report = RuntimeReport((), failed_task_id="tester", error="pytest failed", rounds=1)
    result = runtime.observe_self_improvement(report, "tests/test_agent_runtime.py")

    assert result is not None
    assert calls["report"] is report
    assert calls["history_path"] == tmp_path / "history.jsonl"
    assert calls["target_paths"] == ("tests/test_agent_runtime.py",)
    assert isinstance(calls["control_tower"], FakeTower)


def test_observe_self_improvement_can_enable_bounded_creator_critic(monkeypatch, tmp_path):
    from core import line_development_runtime as runtime

    seen = {}

    def fake_builder(*, max_iterations):
        seen["max_iterations"] = max_iterations
        return object()

    class FakeTower:
        pass

    def fake_cycle(report, history_path, *, target_paths, control_tower):
        seen["control_tower"] = control_tower
        return SimpleNamespace(
            new_signals=(),
            analysis=SimpleNamespace(recurring_patterns=()),
            proposals=(),
            approved_proposals=(),
        )

    monkeypatch.setenv("SELF_IMPROVEMENT_CREATOR_CRITIC", "true")
    monkeypatch.setenv("SELF_IMPROVEMENT_HISTORY_PATH", str(tmp_path / "history.jsonl"))
    monkeypatch.setattr(runtime, "build_creator_critic_loop", fake_builder)
    monkeypatch.setattr(runtime, "ControlTower", lambda **kwargs: FakeTower())
    monkeypatch.setattr(runtime, "run_self_improvement_cycle", fake_cycle)

    report = RuntimeReport((), rounds=1, integration_ready=True)
    result = runtime.observe_self_improvement(report, "tests/test_agent_runtime.py")

    assert result is not None
    assert seen["max_iterations"] == 1
    assert isinstance(seen["control_tower"], FakeTower)
