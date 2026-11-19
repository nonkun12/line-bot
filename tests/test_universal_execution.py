import pytest

from core.agent_specs import AgentLifecycle, AgentSpec, AgentSpecRegistry
from core.execution_pipeline import DefaultPlanner, Manager, WorkRequest
from core.project_registry import DEFAULT_PROJECT, ProjectRecord, ProjectRegistry
from core.task_routing import ProjectResolver, TaskClassifier, TaskMode


def test_classifier_covers_core_work_modes():
    classifier = TaskClassifier()
    assert classifier.classify("自分自身を改善して").mode == TaskMode.SELF_IMPROVEMENT
    assert classifier.classify("開発: TODO管理Webアプリを作って").mode == TaskMode.NEW_SOFTWARE
    assert classifier.classify("調べてレポートして").mode == TaskMode.NON_SOFTWARE
    assert classifier.classify("ai-todo-appを改良して").project_name == "ai-todo-app"


def test_classifier_accepts_slash_qualified_repository_target():
    result = TaskClassifier().classify("nonkun12/my-mcp-serverを改善して")
    assert result.mode == TaskMode.EXISTING_SOFTWARE
    assert result.project_name == "nonkun12/my-mcp-server"


def test_existing_project_resolution_fails_closed():
    registry = ProjectRegistry([
        DEFAULT_PROJECT,
        ProjectRecord(name="ai-todo-app", repository="nonkun12/ai-todo-app"),
    ])
    resolver = ProjectResolver(registry)

    known = resolver.resolve(TaskClassifier().classify("ai-todo-appを改良して"))
    unknown = resolver.resolve(TaskClassifier().classify("unknown-appを改良して"))

    assert known.safe is True
    assert known.repository == "nonkun12/ai-todo-app"
    assert unknown.safe is False
    assert unknown.repository is None


def test_new_software_plan_never_targets_line_bot():
    result = Manager().prepare(WorkRequest("u1", "開発: TODO管理Webアプリを作って"))
    assert result.plan.mode == TaskMode.NEW_SOFTWARE
    assert result.plan.target.repository is None
    assert "create_repository" in result.plan.stages
    assert result.plan.requires_approval is True


def test_self_improvement_resolves_line_bot():
    result = Manager().prepare(WorkRequest("u1", "自分自身を改善して"))
    assert result.plan.mode == TaskMode.SELF_IMPROVEMENT
    assert result.plan.target.repository == "nonkun12/line-bot"
    assert result.plan.target.safe is True


def test_agent_lifecycle_requires_validation_before_enable():
    spec = AgentSpec.create(
        name="stock-monitor",
        purpose="Monitor stock prices",
        input_contract="ticker",
        output_contract="report",
        allowed_tools=("market_data",),
        resource_scope=("market-data",),
        safety_constraints=("read-only",),
        tests=("test_stock_monitor",),
    )
    registry = AgentSpecRegistry([spec])

    with pytest.raises(ValueError):
        spec.transition(AgentLifecycle.ENABLED)

    validated = spec.transition(AgentLifecycle.VALIDATED)
    tested = validated.transition(AgentLifecycle.TESTED)
    reviewed = tested.transition(AgentLifecycle.REVIEWED)
    enabled = reviewed.transition(AgentLifecycle.ENABLED)
    registry.update(enabled)

    assert registry.require("stock-monitor").lifecycle == AgentLifecycle.ENABLED
