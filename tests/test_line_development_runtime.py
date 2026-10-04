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
    assert [name for name, _ in events] == ["restore", "context", "build_plan", "apply"]
    assert state.touched == ["core/example.py"]


def test_implementer_routes_plan_validation_through_bounded_repair(monkeypatch):
    chosen = "core/structured_output.py"
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


def test_implementer_routes_apply_failure_through_bounded_anchor_repair(monkeypatch):
    chosen = "core/structured_output.py"
    plan = {
        "no_change": False,
        "changes": [{"file": chosen, "old": "missing", "new": "replacement"}],
    }
    repaired = {
        "no_change": False,
        "changes": [{"file": chosen, "old": "exact", "new": "replacement"}],
    }
    calls = []

    monkeypatch.setattr(
        runtime.worker,
        "build_plan",
        lambda *args, **kwargs: plan,
    )

    def apply_with_repair(client, instruction, selected, current_plan, context):
        calls.append(("apply", selected, current_plan))
        return repaired, True, "applied", [selected]

    monkeypatch.setattr(runtime.worker, "apply_plan_with_bounded_anchor_repair", apply_with_repair)

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
    assert calls and calls[0][0] == "apply"
    assert state.plan == repaired
    assert state.touched == [chosen]




def test_deterministic_autonomous_test_plan_hand_sign_within_size_bounds(monkeypatch, tmp_path):
    target = tmp_path / "uhip" / "tests" / "test_schema_contracts.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    real_file = runtime.worker.ROOT / "uhip" / "tests" / "test_schema_contracts.py"
    target.write_text(real_file.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "hand-sign-uhip-contract-test")

    plan, err = runtime._deterministic_autonomous_test_plan("uhip/tests/test_schema_contracts.py")

    assert err is None
    assert plan is not None
    assert plan["no_change"] is False
    assert plan["source"] == "deterministic_autonomous_task"
    assert len(plan["changes"]) == 1
    change = plan["changes"][0]
    assert change["file"] == "uhip/tests/test_schema_contracts.py"
    assert len(change["old"]) <= 1200
    assert len(change["new"]) <= 1800
    # Must pass worker.validate_plan cleanly without size/marker repairs
    ok, detail = runtime.worker.validate_plan(plan, "uhip/tests/test_schema_contracts.py")
    assert ok is True
    assert detail == "uhip/tests/test_schema_contracts.py"


def test_deterministic_autonomous_test_plan_no_change_when_test_present(monkeypatch, tmp_path):
    target = tmp_path / "uhip" / "tests" / "test_schema_contracts.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_universal_event_accepts_hand_event_with_recognition_failure(): pass\n", encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "hand-sign-uhip-contract-test")

    plan, err = runtime._deterministic_autonomous_test_plan("uhip/tests/test_schema_contracts.py")

    assert err is None
    assert plan == {"no_change": True, "source": "deterministic_autonomous_task"}


def test_deterministic_autonomous_test_plan_fails_closed_on_anchor_mismatch(monkeypatch, tmp_path):
    target = tmp_path / "uhip" / "tests" / "test_schema_contracts.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# anchor missing completely\n", encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "hand-sign-uhip-contract-test")

    plan, err = runtime._deterministic_autonomous_test_plan("uhip/tests/test_schema_contracts.py")

    assert plan is None
    assert "anchor_count" in err


def test_implementer_applies_deterministic_task_plan_without_llm_repair(monkeypatch, tmp_path):
    chosen = "uhip/tests/test_schema_contracts.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    real_file = runtime.worker.ROOT / chosen
    target.write_text(real_file.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "hand-sign-uhip-contract-test")

    state = runtime.DevelopmentState(
        client=object(),
        instruction="ハンドサイン契約テストを追加して",
        chosen=chosen,
    )
    executor = runtime.DevelopmentExecutor(state)
    task = AgentTask(
        "implementer",
        AgentRole.IMPLEMENTER,
        "Implement the hand-sign test.",
        resources=frozenset({"working-tree"}),
    )

    result = executor.execute(task)

    assert result.success is True
    assert result.summary == "guarded change applied"
    assert state.touched == [chosen]
    updated_text = target.read_text(encoding="utf-8")
    assert "def test_universal_event_accepts_hand_event_with_recognition_failure():" in updated_text


def test_debugger_rejects_llm_mutation_for_deterministic_task(monkeypatch):
    chosen = "uhip/tests/test_schema_contracts.py"
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "hand-sign-uhip-contract-test")

    state = runtime.DevelopmentState(
        client=object(),
        instruction="ハンドサイン契約テストを追加して",
        chosen=chosen,
    )
    executor = runtime.DevelopmentExecutor(state)
    task = AgentTask(
        "debugger",
        AgentRole.DEBUGGER,
        "Retry the failed test.",
        resources=frozenset({"working-tree"}),
    )

    result = executor.execute(task)

    assert result.success is False
    assert "must not be mutated by LLM" in result.summary
