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


def test_deterministic_manager_uses_declared_target_without_llm(monkeypatch):
    task_id = "uhip-confidence-out-of-range-rejection"
    chosen = "uhip/tests/test_schema_contracts.py"
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", task_id)
    monkeypatch.setattr(runtime.worker, "repo_files", lambda: [chosen])

    def forbidden_model_selection(*args, **kwargs):
        raise AssertionError("deterministic task must not call model-backed file selection")

    monkeypatch.setattr(runtime.worker, "choose_file", forbidden_model_selection)
    state = runtime.DevelopmentState(
        client=None,
        instruction="Add the confidence out-of-range schema contract test.",
        autonomous_task_id=task_id,
    )

    result = runtime.DevelopmentExecutor(state).execute(
        AgentTask(
            "manager",
            AgentRole.MANAGER,
            "Select one safe implementation target.",
            resources=frozenset({"target-selection"}),
        )
    )

    assert result.success is True
    assert result.summary == f"selected {chosen}"
    assert state.chosen == chosen


def test_self_improvement_observation_records_locally_without_external_ai(monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_IMPROVEMENT_HISTORY_PATH", str(tmp_path / "history.jsonl"))
    monkeypatch.setenv("SELF_IMPROVEMENT_CREATOR_CRITIC", "true")
    calls = []

    def fake_cycle(report, history_path, *, target_paths, control_tower):
        calls.append((report, history_path, target_paths, control_tower))
        return type("Result", (), {
            "new_signals": (),
            "analysis": type("Analysis", (), {"recurring_patterns": ()})(),
            "proposals": (),
            "approved_proposals": (),
        })()

    def forbidden_provider_initialization(*args, **kwargs):
        raise AssertionError("local-only observation must not initialize external providers")

    monkeypatch.setattr(runtime, "build_creator_critic_loop", forbidden_provider_initialization)
    monkeypatch.setattr(runtime, "run_self_improvement_cycle", fake_cycle)
    monkeypatch.setattr(runtime, "ControlTower", lambda **kwargs: kwargs)

    result = runtime.observe_self_improvement(
        object(),
        "uhip/tests/test_schema_contracts.py",
        allow_external_ai=False,
    )

    assert result is not None
    assert len(calls) == 1
    assert calls[0][1] == tmp_path / "history.jsonl"
    assert calls[0][2] == ("uhip/tests/test_schema_contracts.py",)
    assert calls[0][3]["creator_critic"] is None


def test_deterministic_task_id_does_not_disable_unrelated_self_improvement_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "uhip-confidence-out-of-range-rejection")
    monkeypatch.setenv("SELF_IMPROVEMENT_CREATOR_CRITIC", "false")
    monkeypatch.setenv("SELF_IMPROVEMENT_HISTORY_PATH", str(tmp_path / "history.jsonl"))

    def fake_cycle(report, history_path, *, target_paths, control_tower):
        return type("Result", (), {
            "new_signals": (),
            "analysis": type("Analysis", (), {"recurring_patterns": ()})(),
            "proposals": (),
            "approved_proposals": (),
        })()

    monkeypatch.setattr(runtime, "ControlTower", lambda **kwargs: object())
    monkeypatch.setattr(runtime, "run_self_improvement_cycle", fake_cycle)

    result = runtime.observe_self_improvement(object(), "tests/test_agent_runtime.py")

    assert result is not None


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

    plan, err = runtime._deterministic_autonomous_test_plan("uhip/tests/test_schema_contracts.py", "hand-sign-uhip-contract-test")

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


def test_negative_confidence_plan_rejects_decorated_anchor(monkeypatch, tmp_path):
    chosen = "uhip/tests/test_schema_contracts.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "from pytest import mark\n\n@mark.xfail\n"
        "def test_adapter_schema_rejects_unknown_risk():\n"
        "    pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "hand-sign-uhip-contract-negative-confidence")

    plan, err = runtime._deterministic_autonomous_test_plan(chosen, "hand-sign-uhip-contract-negative-confidence")

    assert plan is None
    assert err == "deterministic_plan_invalid:anchor_not_standalone_def"


def test_negative_confidence_plan_rejects_commented_anchor(monkeypatch, tmp_path):
    chosen = "uhip/tests/test_schema_contracts.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# preserve this test\n\n"
        "def test_adapter_schema_rejects_unknown_risk():\n"
        "    pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "hand-sign-uhip-contract-negative-confidence")

    plan, err = runtime._deterministic_autonomous_test_plan(chosen, "hand-sign-uhip-contract-negative-confidence")

    assert plan is None
    assert err == "deterministic_plan_invalid:anchor_not_standalone_def"


def test_negative_confidence_plan_preserves_existing_test_body_and_is_syntax_safe(monkeypatch, tmp_path):
    chosen = "uhip/tests/test_schema_contracts.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    show = runtime.worker.run(["git", "show", f"HEAD:{chosen}"])
    assert show.returncode == 0
    original = show.stdout
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "hand-sign-uhip-contract-negative-confidence")

    plan, err = runtime._deterministic_autonomous_test_plan(chosen, "hand-sign-uhip-contract-negative-confidence")

    assert err is None
    assert plan is not None
    change = plan["changes"][0]
    candidate = original.replace(change["old"], change["new"], 1)
    compile(candidate, chosen, "exec")
    assert candidate.count("def test_universal_event_accepts_zero_confidence_hand_event():") == 1
    assert candidate.count("def test_adapter_schema_rejects_unknown_risk():") == 1
    assert "    adapter = {" in candidate
    assert "    with pytest.raises(jsonschema.ValidationError):" in candidate
    assert candidate.index(
        "def test_universal_event_accepts_zero_confidence_hand_event():"
    ) < candidate.index("def test_adapter_schema_rejects_unknown_risk():")


def test_queue_progress_empty_queue_plan_is_deterministic(monkeypatch, tmp_path):
    target = "tests/test_distributed_loop_queue_progress.py"
    path = tmp_path / target
    path.parent.mkdir(parents=True)
    path.write_text(
        chr(10).join([
            "from pathlib import Path",
            "import json",
            "from scripts.distributed_loop_queue_progress import calculate_progress",
            "",
            "def test_progress_uses_runtime_queue_and_counts_refill_tasks(tmp_path: Path):",
            "    pass",
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)
    plan, err = runtime._deterministic_autonomous_test_plan(
        target, "distributed-loop-queue-progress-empty-queue-regression-v2"
    )
    assert err is None
    assert plan is not None
    assert plan["source"] == "deterministic_autonomous_task"
    assert "test_empty_runtime_queue_reports_zero_progress_for_not_run_v2" in plan["changes"][0]["new"]


def test_deterministic_autonomous_test_plan_no_change_when_test_present(monkeypatch, tmp_path):
    target = tmp_path / "uhip" / "tests" / "test_schema_contracts.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_universal_event_accepts_hand_event_with_recognition_failure(): pass\n", encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "hand-sign-uhip-contract-test")

    plan, err = runtime._deterministic_autonomous_test_plan("uhip/tests/test_schema_contracts.py", "hand-sign-uhip-contract-test")

    assert err is None
    assert plan == {"no_change": True, "source": "deterministic_autonomous_task"}


def test_deterministic_autonomous_test_plan_fails_closed_on_anchor_mismatch(monkeypatch, tmp_path):
    target = tmp_path / "uhip" / "tests" / "test_schema_contracts.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# anchor missing completely\n", encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "hand-sign-uhip-contract-test")

    plan, err = runtime._deterministic_autonomous_test_plan("uhip/tests/test_schema_contracts.py", "hand-sign-uhip-contract-test")

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


def test_phase_start_deterministic_task_plan_is_syntax_safe(monkeypatch, tmp_path):
    chosen = "uhip/tests/test_schema_contracts.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "def test_existing_event():\n"
        "    event = {}\n"
        "    validate(event, EVENT_SCHEMA)\n\n\n"
        "def test_universal_event_rejects_application_specific_command():\n"
        "    pass\n"
    )
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    plan, err = runtime._deterministic_autonomous_test_plan(
        chosen,
        "hand-sign-uhip-contract-phase-start",
    )

    assert err is None
    assert plan is not None
    assert plan["no_change"] is False
    assert plan["source"] == "deterministic_autonomous_task"
    change = plan["changes"][0]
    candidate = original.replace(change["old"], change["new"], 1)
    compile(candidate, chosen, "exec")
    assert candidate.count("def test_universal_event_accepts_hand_event_with_phase_start():") == 1
    assert '"phase": "start"' in candidate


def test_new_distributed_queue_tasks_have_deterministic_plans(monkeypatch, tmp_path):
    cases = [
        (
            "hand-sign-uhip-contract-left-hand",
            "uhip/tests/test_schema_contracts.py",
            "def test_universal_event_rejects_application_specific_command():\n    pass\n",
            '"label": "left"',
            '"mirrored": False',
        ),
        (
            "router-regression-jobs-market-metadata",
            "tests/test_management_router.py",
            "def test_preserves_multi_specialist_candidates_and_priority() -> None:\n    pass\n",
            'decision = route(ManagementRequest("u", "JobsとNYダウの情報を一緒に教えて"))',
            '["market", "jobs"]',
        ),
        (
            "router-regression-english-casefold",
            "tests/test_management_router.py",
            "def test_preserves_multi_specialist_candidates_and_priority() -> None:\n    pass\n",
            'eNgLiShで会話したい',
            "Specialist.ENGLISH",
        ),
        (
            "uhip-confidence-out-of-range-rejection",
            "uhip/tests/test_schema_contracts.py",
            "def test_universal_event_rejects_application_specific_command():\n    pass\n",
            '"calibrated": 1.01',
            "confidence-range-session-20261009",
        ),
        (
            "router-regression-stock-jobs-priority",
            "tests/test_management_router.py",
            "def test_preserves_market_priority_over_jobs_for_mixed_request() -> None:\n    pass\n",
            "test_router_regression_stock_jobs_priority_distributed_loop",
            '["stocks", "jobs"]',
        ),
        (
            "router-regression-market-channel-metadata",
            "tests/test_management_router.py",
            "def test_normalizes_full_width_input_and_preserves_channel_metadata() -> None:\n    pass\n",
            "test_router_regression_market_channel_metadata_distributed_loop",
            "distributed-loop-regression",
        ),
        (
            "macos-readiness-audit-no-secret-leak",
            "tests/test_macos_kanban_obsidian_readiness.py",
            "def test_load_env_file_ignores_comments_and_strips_quotes(tmp_path: Path):\n    pass\n",
            "secret-canary-never-logged",
            'report["project_writes"] == 0',
        ),
    ]

    for task_id, chosen, original, expected_one, expected_two in cases:
        target = tmp_path / chosen
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(original, encoding="utf-8")
        monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

        plan, err = runtime._deterministic_autonomous_test_plan(chosen, task_id)

        assert err is None
        assert plan is not None
        assert plan["no_change"] is False
        change = plan["changes"][0]
        candidate = original.replace(change["old"], change["new"], 1)
        compile(candidate, chosen, "exec")
        assert expected_one in candidate
        assert expected_two in candidate


def test_confidence_rejection_plan_is_idempotent_when_test_exists(monkeypatch, tmp_path):
    chosen = "uhip/tests/test_schema_contracts.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "def test_universal_event_rejects_out_of_range_calibrated_confidence():\n    pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    plan, err = runtime._deterministic_autonomous_test_plan(
        chosen,
        "uhip-confidence-out-of-range-rejection",
    )

    assert err is None
    assert plan == {"no_change": True, "source": "deterministic_autonomous_task"}


def test_repairer_fails_closed_for_deterministic_task_without_llm(monkeypatch):
    chosen = "uhip/tests/test_schema_contracts.py"
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "uhip-confidence-out-of-range-rejection")

    state = runtime.DevelopmentState(
        client=object(),
        instruction="Add the confidence out-of-range schema test.",
        chosen=chosen,
    )
    executor = runtime.DevelopmentExecutor(state)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM plan generation must not run for deterministic tasks")

    monkeypatch.setattr(runtime.worker, "build_plan", fail_if_called)
    task = AgentTask(
        "repairer",
        AgentRole.REPAIRER,
        "Retry the failed deterministic test.",
        resources=frozenset({"working-tree"}),
    )

    result = executor.execute(task)

    assert result.success is False
    assert result.summary == "deterministic test failure; no LLM repair"


def test_router_regression_plans_are_idempotent_when_tests_exist(monkeypatch, tmp_path):
    chosen = "tests/test_management_router.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "def test_router_regression_stock_jobs_priority_distributed_loop():\n    pass\n\n"
        "def test_router_regression_market_channel_metadata_distributed_loop():\n    pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    for task_id in (
        "router-regression-stock-jobs-priority",
        "router-regression-market-channel-metadata",
    ):
        plan, err = runtime._deterministic_autonomous_test_plan(chosen, task_id)
        assert err is None
        assert plan == {"no_change": True, "source": "deterministic_autonomous_task"}

def test_refactorer_receives_current_repair_task_context(monkeypatch):
    chosen = "core/example.py"
    task_context = "Reviewer failure: stale assertion remains in test_example"
    state = runtime.DevelopmentState(
        client=object(),
        instruction="Fix the example implementation",
    )
    state.chosen = chosen
    state.touched = [chosen]
    state.test_output = "Old test output unrelated to reviewer failure"
    calls = {}

    def build_plan(client, instruction, path, context, test_output):
        calls["instruction"] = instruction
        calls["test_output"] = test_output
        return {
            "no_change": False,
            "changes": [{"file": path, "old": "before", "new": "after"}],
        }

    monkeypatch.setattr(worker, "build_plan", build_plan)
    monkeypatch.setattr(worker, "context_for", lambda path: "current source context")
    monkeypatch.setattr(
        worker,
        "validate_plan_with_bounded_repairs",
        lambda client, instruction, path, plan, context: (plan, True, "validated"),
    )
    monkeypatch.setattr(
        worker,
        "apply_plan_with_bounded_anchor_repair",
        lambda client, instruction, path, plan, context: (
            plan,
            True,
            "applied",
            [path],
        ),
    )

    result = runtime.DevelopmentExecutor(state).execute(
        AgentTask(
            "refactor:reviewer-failure",
            AgentRole.REFACTORER,
            task_context,
            frozenset({"working-tree"}),
        )
    )

    assert result.success
    assert task_context in calls["instruction"]
    assert "Fix the example implementation" in calls["instruction"]
    assert task_context in calls["test_output"]
    assert "Old test output unrelated to reviewer failure" in calls["test_output"]



def test_ai_speaker_empty_transcript_plan_handles_existing_unannotated_test(monkeypatch, tmp_path):
    chosen = "tests/test_ai_speaker.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "class FakeBrain:\n"
        "    def __init__(self): self.requests = []\n"
        "def test_ai_speaker_rejects_empty_transcript():\n"
        "    brain = FakeBrain()\n"
        "    try:\n"
        '        raise ValueError("speech transcript must not be empty")\n'
        "    except ValueError as exc:\n"
        '        assert str(exc) == "speech transcript must not be empty"\n'
        "    else:\n"
        '        raise AssertionError("empty transcript must fail closed")\n'
    )
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    plan, err = runtime._deterministic_autonomous_test_plan(
        chosen, "ai-speaker-empty-transcript-no-brain-call"
    )

    assert err is None
    assert plan is not None
    assert plan["no_change"] is False
    change = plan["changes"][0]
    assert change["old"] == '        raise AssertionError("empty transcript must fail closed")\n'
    candidate = original.replace(change["old"], change["new"], 1)
    compile(candidate, chosen, "exec")
    assert candidate.count("def test_ai_speaker_rejects_empty_transcript()") == 1
    assert "    assert brain.requests == []\n" in candidate


def test_ai_speaker_empty_transcript_plan_is_idempotent_after_assertion(monkeypatch, tmp_path):
    chosen = "tests/test_ai_speaker.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "def test_ai_speaker_rejects_empty_transcript():\n"
        "    brain = FakeBrain()\n"
        '    assert brain.requests == []\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    plan, err = runtime._deterministic_autonomous_test_plan(
        chosen, "ai-speaker-empty-transcript-no-brain-call"
    )

    assert err is None
    assert plan == {"no_change": True, "source": "deterministic_autonomous_task"}


def test_refill_malformed_completed_state_plan_is_syntax_safe_and_bounded(monkeypatch, tmp_path):
    chosen = "tests/test_autonomous_task_refill.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    anchor = "def test_refill_fails_closed_when_recovery_ai_state_is_missing(tmp_path: Path):\n    pass\n"
    target.write_text(anchor, encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    plan, err = runtime._deterministic_autonomous_test_plan(
        chosen, "refill-rejects-malformed-completed-state"
    )

    assert err is None
    assert plan is not None
    assert plan["source"] == "deterministic_autonomous_task"
    assert plan["no_change"] is False
    change = plan["changes"][0]
    assert change["file"] == chosen
    assert len(change["old"]) <= 1200
    assert len(change["new"]) <= 1800
    candidate = anchor.replace(change["old"], change["new"], 1)
    compile(candidate, chosen, "exec")
    assert "test_refill_fails_closed_on_non_string_completed_state" in candidate
    assert "completed state must be a string list" in candidate
    assert worker.validate_plan(plan, chosen) == (True, chosen)


def test_self_improvement_history_plan_is_syntax_safe_and_bounded(monkeypatch, tmp_path):
    chosen = "tests/test_self_improvement_state.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    anchor = "def test_sanitizer_discards_raw_error_text_and_unknown_fields():\n    pass\n"
    target.write_text(anchor, encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    plan, err = runtime._deterministic_autonomous_test_plan(
        chosen, "self-improvement-history-malformed-jsonl-regression"
    )

    assert err is None
    assert plan is not None
    assert plan["source"] == "deterministic_autonomous_task"
    assert plan["no_change"] is False
    change = plan["changes"][0]
    assert change["file"] == chosen
    assert len(change["old"]) <= 1200
    assert len(change["new"]) <= 1800
    candidate = anchor.replace(change["old"], change["new"], 1)
    compile(candidate, chosen, "exec")
    assert "test_read_jsonl_skips_malformed_rows_and_preserves_valid_order" in candidate
    assert "\\n" in candidate
    assert worker.validate_plan(plan, chosen) == (True, chosen)




def test_three_new_refill_seed_plans_are_syntax_safe_and_bounded(tmp_path, monkeypatch):
    chosen = "tests/test_autonomous_task_refill.py"
    cases = [
        (
            "refill-rejects-nonobject-recovery-task-map",
            "def test_refill_fails_closed_on_invalid_recovery_ai_schema(tmp_path: Path):",
            "test_refill_fails_closed_on_nonobject_recovery_task_map",
        ),
        (
            "refill-rejects-boolean-catalog-addition-cap",
            "def test_refill_rejects_duplicate_catalog_ids(tmp_path: Path):",
            "test_refill_rejects_boolean_catalog_addition_cap",
        ),
        (
            "refill-rejects-non-ascii-task-id",
            "def test_refill_rejects_duplicate_existing_queue_ids(tmp_path: Path):",
            "test_refill_rejects_non_ascii_task_id",
        ),
        (
            "refill-preserves-catalog-order-within-addition-cap",
            "def test_refill_reports_catalog_exhaustion_by_durable_state(tmp_path: Path):",
            "test_refill_preserves_catalog_order_within_addition_cap",
        ),
    ]
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    for task_id, anchor, expected_name in cases:
        original = anchor + "\n    pass\n"
        target.write_text(original, encoding="utf-8")
        plan, err = runtime._deterministic_autonomous_test_plan(chosen, task_id)

        assert err is None, task_id
        assert plan is not None, task_id
        assert plan["no_change"] is False, task_id
        change = plan["changes"][0]
        assert change["file"] == chosen
        assert len(change["old"]) <= 1200
        assert len(change["new"]) <= 1800
        candidate = original.replace(change["old"], change["new"], 1)
        compile(candidate, chosen, "exec")
        assert expected_name in candidate
        assert worker.validate_plan(plan, chosen) == (True, chosen)


def test_four_reviewed_refill_tasks_have_deterministic_bounded_plans(tmp_path, monkeypatch):
    cases = [
        (
            "distributed-loop-dispatch-duplicate-active-run-guard-regression",
            "tests/test_distributed_loop_trigger.py",
            "def test_dispatch_acknowledges_only_after_run_is_visible(monkeypatch):",
            "test_dispatch_does_not_post_when_run_is_already_active_distributed_loop",
        ),
        (
            "proposal-generator-resume-review-exclusion-regression",
            "tests/test_autonomous_task_proposals.py",
            "def test_approved_tasks_respect_remaining_queue_capacity(tmp_path):",
            "test_approved_registered_task_is_not_queued_when_resume_requires_review",
        ),
        (
            "queue-progress-ignores-unrelated-pass-results-regression",
            "tests/test_distributed_loop_queue_progress.py",
            "def test_progress_rejects_duplicate_queue_ids(tmp_path: Path):",
            "test_progress_ignores_pass_and_no_change_results_outside_runtime_queue",
        ),
        (
            "proposal-generator-conflicting-catalog-definitions-regression",
            "tests/test_autonomous_task_proposals.py",
            "def test_fails_closed_on_missing_recovery_state(tmp_path):",
            "test_conflicting_duplicate_catalog_definitions_fail_closed",
        ),
    ]
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    for task_id, chosen, anchor_line, expected_name in cases:
        target = tmp_path / chosen
        target.parent.mkdir(parents=True, exist_ok=True)
        anchor = anchor_line + "\n"
        original = anchor + "    pass\n"
        target.write_text(original, encoding="utf-8")

        plan, err = runtime._deterministic_autonomous_test_plan(chosen, task_id)

        assert err is None, task_id
        assert plan is not None, task_id
        assert plan["no_change"] is False, task_id
        change = plan["changes"][0]
        assert change["file"] == chosen
        assert change["old"] == anchor
        assert len(change["old"]) <= 1200
        assert len(change["new"]) <= 1800
        candidate = original.replace(change["old"], change["new"], 1)
        compile(candidate, chosen, "exec")
        assert expected_name in candidate
        assert worker.validate_plan(plan, chosen) == (True, chosen)
        if task_id == "queue-progress-ignores-unrelated-pass-results-regression":
            assert r'+ "\n" +' in change["new"]
            assert r'+ "\n", encoding="utf-8")' in change["new"]


def test_refill_regression_task_builds_one_bounded_deterministic_change(monkeypatch, tmp_path):
    chosen = "tests/test_autonomous_task_refill.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        chr(10).join([
            "def test_refill_reports_catalog_exhaustion_by_durable_state(tmp_path: Path):",
            "    pass",
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    plan, err = runtime._deterministic_autonomous_test_plan(
        chosen, "loop-refill-empty-catalog-next-safe-test-20261023"
    )

    assert err is None
    assert plan is not None
    assert plan["no_change"] is False
    assert plan["source"] == "deterministic_autonomous_task"
    assert len(plan["changes"]) == 1
    change = plan["changes"][0]
    assert change["file"] == chosen
    assert len(change["old"]) <= 1200
    assert len(change["new"]) <= 1800
    compile(target.read_text(encoding="utf-8").replace(change["old"], change["new"], 1), chosen, "exec")


def test_priority_boundary_task_uses_deterministic_registered_target(monkeypatch, tmp_path):
    chosen = "tests/test_control_tower_decision.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "def test_priority_rejects_bool_float_and_out_of_range_values():\\n    pass\\n\\n"
        "def test_priority_accepts_integer_boundaries():\\n    pass\\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    assert runtime._DETERMINISTIC_AUTONOMOUS_TASK_TARGETS[
        "control-tower-decision-priority-type-boundaries"
    ] == chosen
    plan, error = runtime._deterministic_autonomous_test_plan(
        chosen, "control-tower-decision-priority-type-boundaries"
    )

    assert error is None
    assert plan == {"no_change": True, "source": "deterministic_autonomous_task"}


def test_priority_boundary_task_fails_closed_when_regression_tests_missing(monkeypatch, tmp_path):
    chosen = "tests/test_control_tower_decision.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_existing_case():\\n    pass\\n", encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    plan, error = runtime._deterministic_autonomous_test_plan(
        chosen, "control-tower-decision-priority-type-boundaries"
    )

    assert plan is None
    assert error == "required_regression_test_missing:priority_boundaries"

def test_safe_continuation_depth_four_task_has_deterministic_bounded_plan(tmp_path, monkeypatch):
    chosen = "tests/test_continuous_distributed_loop_workflow.py"
    anchor = "def test_continuation_depth_missing_fails_closed(tmp_path):\n"
    original = anchor + "    pass\n\n"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    plan, error = runtime._deterministic_autonomous_test_plan(
        chosen, "safe-continuation-depth-four-regression-20261026"
    )

    assert error is None
    assert plan is not None
    assert plan["source"] == "deterministic_autonomous_task"
    assert plan["no_change"] is False
    change = plan["changes"][0]
    assert change["file"] == chosen
    assert len(change["old"]) <= 1200
    assert len(change["new"]) <= 1800
    candidate = original.replace(change["old"], change["new"], 1)
    compile(candidate, chosen, "exec")
    assert "test_safe_continuation_depth_guard_accepts_depth_four" in candidate
    assert worker.validate_plan(plan, chosen) == (True, chosen)
