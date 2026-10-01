from core import line_development_runtime as runtime
from core.multi_agent import AgentRole, AgentTask
from scripts import line_development_worker_v2 as worker


def test_explicit_comment_plan_is_deterministic(tmp_path, monkeypatch):
    target = tmp_path / "line_development.py"
    target.write_text("_WORKFLOW_FILE = \".github/workflows/line-development.yml\"\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    plan = runtime._explicit_comment_plan(
        'line_development.py に「LINE自動開発E2E」というコメントを1行追加して、pytestを実行してください',
        'line_development.py',
    )
    assert plan is not None
    assert plan["no_change"] is False
    assert plan["source"] == "deterministic_self_test"
    change = plan["changes"][0]
    assert change["file"] == "line_development.py"
    assert len(change["old"]) <= 1200
    assert len(change["new"]) <= 1800
    assert change["new"].endswith("# LINE自動開発E2E\n")
    assert worker.validate_plan(plan, "line_development.py") == (
        True,
        "line_development.py",
    )


def test_explicit_comment_plan_is_idempotent(tmp_path, monkeypatch):
    target = tmp_path / "line_development.py"
    target.write_text("_WORKFLOW_FILE = \".github/workflows/line-development.yml\"\n# LINE自動開発E2E\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    plan = runtime._explicit_comment_plan(
        'line_development.py に「LINE自動開発E2E」というコメントを1行追加して',
        "line_development.py",
    )

    assert plan == {"no_change": True, "source": "deterministic_self_test"}


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


def test_debugger_restores_before_building_real_worker_plan(monkeypatch):
    state = runtime.DevelopmentState(client=object(), instruction="fix the failing implementation")
    state.chosen = "core/example.py"
    state.touched = ["core/example.py"]
    events = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def restore(paths):
        events.append(("restore", tuple(paths)))
        state_restored[0] = True

    state_restored = [False]

    def context_for(path):
        assert state_restored[0], "context_for must run after restore"
        events.append(("context", path))
        return "clean baseline context"

    def build_plan(client, instruction, chosen, context, test_output):
        assert state_restored[0], "build_plan must run after restore"
        assert context == "clean baseline context"
        events.append(("build_plan", test_output))
        return {
            "no_change": False,
            "changes": [{"file": chosen, "old": "clean", "new": "fixed"}],
        }

    def validate_plan_with_bounded_repairs(client, instruction, chosen, plan, context):
        events.append(("validate", chosen))
        return plan, True, chosen

    def apply_plan(plan):
        events.append(("apply", plan["changes"][0]["file"]))
        return True, "ok", [plan["changes"][0]["file"]]

    monkeypatch.setattr(worker, "restore", restore)
    monkeypatch.setattr(worker, "context_for", context_for)
    monkeypatch.setattr(worker, "build_plan", build_plan)
    monkeypatch.setattr(worker, "apply_plan", apply_plan)

    executor = runtime.DevelopmentExecutor(state)
    result = executor.execute(
        AgentTask(
            "debug:1:tester",
            AgentRole.DEBUGGER,
            "Analyze and fix the test failure: anchor mismatch",
            frozenset({"working-tree"}),
        )
    )

    assert result.success
    assert [name for name, _ in events] == ["restore", "context", "build_plan", "validate", "apply"]
    assert state.touched == ["core/example.py"]


def test_implementer_routes_plan_validation_through_bounded_repair(monkeypatch):
    chosen = "tests/test_management_router.py"
    rejected = {
        "no_change": False,
        "changes": [{"file": chosen, "old": "old", "new": "x" * 2000}],
    }
    repaired = {
        "no_change": False,
        "changes": [{"file": chosen, "old": "def target():\n    old\n", "new": "def target():\n    new\n"}],
    }
    calls = []

    monkeypatch.setattr(
        runtime.worker,
        "build_plan",
        lambda *args, **kwargs: rejected,
    )

    def repair(*args, **kwargs):
        calls.append("repair")
        return repaired

    monkeypatch.setattr(runtime.worker, "repair_size_plan", repair)
    monkeypatch.setattr(
        runtime.worker,
        "apply_plan",
        lambda plan: (True, "applied", [chosen]),
    )

    state = runtime.DevelopmentState(
        client=object(),
        instruction="tests/test_management_router.py を最小修正",
        chosen=chosen,
    )
    executor = runtime.DevelopmentExecutor(state)
    task = AgentTask(
        "implementer",
        AgentRole.IMPLEMENTER,
        "Implement the requested test change.",
        resources=frozenset({"working-tree"}),
    )

    result = executor.execute(task)

    assert result.success
    assert result.summary == "guarded change applied"
    assert calls == ["repair"]
    assert state.plan == repaired
    assert state.touched == [chosen]

