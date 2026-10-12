from core import line_development_runtime as runtime
from scripts import line_development_worker_v2 as worker


def test_explicit_comment_plan_is_deterministic(tmp_path, monkeypatch):
    target = tmp_path / "tests" / "test_line_development.py"
    target.parent.mkdir(parents=True)
    target.write_text("from line_development import extract_development_instruction\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    plan = runtime._explicit_comment_plan(
        'tests/test_line_development.py に「LINE自動開発E2E」というコメントを1行追加して、pytestを実行してください',
        'tests/test_line_development.py',
    )
    assert plan is not None
    assert plan["no_change"] is False
    change = plan["changes"][0]
    assert change["file"] == "tests/test_line_development.py"
    assert len(change["old"]) <= 1200
    assert len(change["new"]) <= 1800
    assert change["new"].endswith("# LINE自動開発E2E\n")
    assert worker.validate_plan(plan, "tests/test_line_development.py") == (
        True,
        "tests/test_line_development.py",
    )


def test_explicit_comment_plan_is_idempotent(tmp_path, monkeypatch):
    target = tmp_path / "tests" / "test_line_development.py"
    target.parent.mkdir(parents=True)
    target.write_text("from example import value\n# LINE自動開発E2E\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    plan = runtime._explicit_comment_plan(
        'tests/test_line_development.py に「LINE自動開発E2E」というコメントを1行追加して',
        "tests/test_line_development.py",
    )

    assert plan == {"no_change": True}


def test_validate_plan_rejects_oversized_change():
    plan = {
        "no_change": False,
        "changes": [
            {
                "file": "tests/test_line_development.py",
                "old": "x" * 1201,
                "new": "y",
            }
        ],
    }

    assert worker.validate_plan(plan, "tests/test_line_development.py") == (
        False,
        "change_too_large",
    )


def test_fallback_safe_target_prefers_management_router_test():
    files = [
        "tests/test_line_development_runtime.py",
        "tests/test_management_router.py",
        "core/management_router.py",
    ]

    assert runtime._fallback_safe_target(files) == "tests/test_management_router.py"


def test_fallback_safe_target_returns_none_without_preferred_targets():
    assert runtime._fallback_safe_target(["core/example.py"]) is None

def _assert_quality_agent_receives_task_context(monkeypatch, role, instruction):
    from core.multi_agent import AgentRole, AgentTask

    captured = {}

    def fake_build_plan(client, prompt, chosen, context, test_output):
        captured["prompt"] = prompt
        captured["test_output"] = test_output
        return {
            "no_change": False,
            "changes": [{"file": chosen, "old": "old", "new": "new"}],
        }

    monkeypatch.setattr(worker, "build_plan", fake_build_plan)
    monkeypatch.setattr(worker, "validate_plan", lambda plan, chosen: (True, chosen))
    monkeypatch.setattr(worker, "context_for", lambda chosen: "target context")
    monkeypatch.setattr(worker, "restore", lambda touched: None)
    monkeypatch.setattr(worker, "apply_plan", lambda plan: (True, "applied", ["tests/example.py"]))

    state = runtime.DevelopmentState(
        client=object(),
        instruction="Original user request",
        chosen="tests/example.py",
        touched=["tests/example.py"],
        test_output="STALE TEST OUTPUT",
    )
    task = AgentTask(
        "quality-context-test",
        role,
        instruction,
        frozenset({"tests/example.py"}),
    )

    result = runtime.DevelopmentExecutor(state).execute(task)

    assert result.success
    assert instruction in captured["prompt"]
    assert "Original user request" in captured["prompt"]
    assert instruction in captured["test_output"]


def test_debugger_receives_reviewer_failure_context(monkeypatch):
    from core.multi_agent import AgentRole

    failure = "Reviewer failure: missing edge-case handling"
    _assert_quality_agent_receives_task_context(monkeypatch, AgentRole.DEBUGGER, failure)


def test_refactorer_receives_current_task_context(monkeypatch):
    from core.multi_agent import AgentRole

    instruction = "Refactor after reviewer failure: missing edge-case handling"
    _assert_quality_agent_receives_task_context(monkeypatch, AgentRole.REFACTORER, instruction)

