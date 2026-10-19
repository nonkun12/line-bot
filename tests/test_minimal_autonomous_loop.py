from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import run_minimal_autonomous_loop as loop
from scripts.run_minimal_autonomous_loop import load_completed, load_tasks, stopped


def test_queue_is_nonempty_and_run_limit_is_bounded():
    queue_data = json.loads(loop.QUEUE.read_text(encoding="utf-8"))
    tasks = load_tasks()
    assert tasks
    assert 1 <= queue_data["max_tasks_per_run"] <= 4
    assert all(task["id"] and task["instruction"] and task["allowed_paths"] for task in tasks)


def test_selection_head_snapshot_precedes_queue_read(monkeypatch):
    events = []

    class _Queue:
        def read_text(self, encoding="utf-8"):
            events.append("queue")
            return json.dumps({"max_tasks_per_run": 1})

    monkeypatch.setattr(loop, "QUEUE", _Queue())
    monkeypatch.setattr(loop, "_git_head", lambda: events.append("head") or "a" * 40)
    monkeypatch.setattr(loop.sys, "argv", ["run_minimal_autonomous_loop", "--max-tasks", "4"])

    try:
        loop.main()
    except SystemExit as exc:
        assert "exceeds queue max_tasks_per_run" in str(exc)
    else:
        raise AssertionError("expected run-limit rejection")

    assert events == ["head", "queue"]


def test_deterministic_target_resolves_when_project_root_is_not_on_sys_path(monkeypatch):
    root_text = str(loop.ROOT)
    monkeypatch.setattr(loop.sys, "path", [entry for entry in loop.sys.path if entry != root_text])
    task = {
        "id": "uhip-confidence-out-of-range-rejection",
        "instruction": "test",
        "allowed_paths": ["uhip/tests/test_schema_contracts.py"],
    }

    assert root_text not in loop.sys.path
    assert loop._deterministic_target_for_task(task) == "uhip/tests/test_schema_contracts.py"
    assert root_text in loop.sys.path


def test_produced_head_rejects_traversal_allowed_paths(monkeypatch):
    monkeypatch.setattr(loop, "_git_head", lambda: "b" * 40)
    monkeypatch.setattr(loop, "_git_checked", lambda *args: (0, "tests/test_a.py"))
    for path in ("../tests/test_a.py", "tests/../core/x.py", "/tmp/x.py", "tests\\\\test_a.py"):
        assert loop._verify_produced_head("a" * 40, "b" * 40, [path]) == (False, "allowed_paths_invalid")


def test_produced_head_requires_exact_file_allowlist(monkeypatch):
    monkeypatch.setattr(loop, "_git_head", lambda: "b" * 40)
    monkeypatch.setattr(loop, "_git_checked", lambda *args: (0, "tests/sub/test_a.py"))
    assert loop._verify_produced_head("a" * 40, "b" * 40, ["tests"]) == (False, "diff_outside_allowed_paths")
    monkeypatch.setattr(loop, "_git_checked", lambda *args: (0, "tests/test_a.py"))
    assert loop._verify_produced_head("a" * 40, "b" * 40, ["tests/test_a.py"]) == (True, "")


def test_kill_switch_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTONOMOUS_LOOP_STOP", "true")
    assert stopped(tmp_path / "missing-stop-file")


def test_kill_switch_file(tmp_path: Path):
    stop = tmp_path / "stop"
    stop.write_text("STOP\n", encoding="utf-8")
    assert stopped(stop)


def test_no_kill_switch_by_default(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AUTONOMOUS_LOOP_STOP", raising=False)
    assert not stopped(tmp_path / "missing-stop-file")


def test_unknown_nonempty_stop_value_fails_closed(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTONOMOUS_LOOP_STOP", "STOP")
    assert stopped(tmp_path / "missing")


def test_completed_state_filters_known_task_ids(tmp_path: Path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": ["t1", "t2"]}), encoding="utf-8")
    assert load_completed(state) == {"t1", "t2"}


def test_invalid_completed_state_fails_closed(tmp_path: Path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": "t1"}), encoding="utf-8")
    try:
        load_completed(state)
    except ValueError as exc:
        assert "completed" in str(exc)
    else:
        raise AssertionError("expected invalid state rejection")


class _FakeProcess:
    def __init__(self, env, writer, returncode=0):
        self.pid = 12345
        self.returncode = None
        self._writer = writer
        self._final_returncode = returncode
        writer(env)

    def poll(self):
        if self.returncode is None:
            self.returncode = self._final_returncode
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = self._final_returncode
        return self.returncode


def test_invalid_summary_halts(monkeypatch, tmp_path: Path):
    task = {"id": "invalid-summary-test", "instruction": "test", "allowed_paths": ["tests/test_one.py"]}
    monkeypatch.setattr(loop, "_git_head", lambda: "a" * 40)

    def fake_popen(cmd, cwd, env, text, start_new_session):
        summary = Path(env["AUTONOMOUS_SUMMARY_PATH"])
        summary.write_text("[]", encoding="utf-8")
        return _FakeProcess(env, lambda _: None)

    monkeypatch.setattr(loop.subprocess, "Popen", fake_popen)
    result = loop.run_task(task, 1, tmp_path / "stop", summary_dir=tmp_path)
    assert result["status"] == "FAIL"
    assert result["failure_reason"] == "summary_not_object"


def test_no_change_is_not_pass(monkeypatch, tmp_path: Path):
    task = {"id": "no-change-test", "instruction": "test", "allowed_paths": ["tests/test_one.py"]}
    sha = "b" * 40
    monkeypatch.setattr(loop, "_git_head", lambda: sha)

    def fake_popen(cmd, cwd, env, text, start_new_session):
        summary = Path(env["AUTONOMOUS_SUMMARY_PATH"])
        summary.write_text(
            json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "PASS",
                "exit_code": 0,
                "base_sha": sha,
                "produced_sha": sha,
                "task_id": task["id"],
                "run_nonce": env["AUTONOMOUS_RUN_NONCE"],
            }),
            encoding="utf-8",
        )
        return _FakeProcess(env, lambda _: None)

    monkeypatch.setattr(loop.subprocess, "Popen", fake_popen)
    result = loop.run_task(task, 1, tmp_path / "stop", summary_dir=tmp_path)
    assert result["status"] == "NO_CHANGE"
    assert result["failure_reason"] == "no_change"


def _capture_task_provider_env(monkeypatch, tmp_path: Path, task: dict[str, object]) -> tuple[dict[str, str], dict[str, object]]:
    observed: dict[str, str] = {}
    sha = "e" * 40
    monkeypatch.setattr(loop, "_git_head", lambda: sha)

    def fake_popen(cmd, cwd, env, text, start_new_session):
        provider_keys = {
            "GROQ_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "OPENROUTER_API_KEY",
            "DEEPSEEK_API_KEY",
            "MISTRAL_API_KEY",
            "COHERE_API_KEY",
        }
        observed.update({key: env[key] for key in provider_keys if key in env})
        summary = Path(env["AUTONOMOUS_SUMMARY_PATH"])
        summary.write_text(
            json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "PASS",
                "exit_code": 0,
                "base_sha": sha,
                "produced_sha": sha,
                "task_id": task["id"],
                "run_nonce": env["AUTONOMOUS_RUN_NONCE"],
            }),
            encoding="utf-8",
        )
        return _FakeProcess(env, lambda _: None)

    monkeypatch.setattr(loop.subprocess, "Popen", fake_popen)
    result = loop.run_task(task, 1, tmp_path / "stop", summary_dir=tmp_path)
    return observed, result


def test_deterministic_task_subprocess_has_no_provider_credentials(monkeypatch, tmp_path: Path):
    task = {
        "id": "uhip-confidence-out-of-range-rejection",
        "instruction": "Run the bounded schema contract task.",
        "allowed_paths": ["uhip/tests/test_schema_contracts.py"],
    }
    monkeypatch.setenv("GROQ_API_KEY", "test-only-sentinel")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-sentinel")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-sentinel")

    provider_env, result = _capture_task_provider_env(monkeypatch, tmp_path, task)

    assert result["status"] == "NO_CHANGE"
    assert provider_env == {}


def test_unmapped_task_keeps_provider_credentials_for_its_own_policy(monkeypatch, tmp_path: Path):
    task = {
        "id": "future-model-assisted-task",
        "instruction": "Run a non-deterministic task.",
        "allowed_paths": ["tests/test_line_development_runtime.py"],
    }
    monkeypatch.setenv("GROQ_API_KEY", "test-only-sentinel")

    provider_env, result = _capture_task_provider_env(monkeypatch, tmp_path, task)

    assert result["status"] == "NO_CHANGE"
    assert provider_env["GROQ_API_KEY"] == "test-only-sentinel"


def test_summary_identity_mismatch_halts(monkeypatch, tmp_path: Path):
    task = {"id": "identity-test", "instruction": "test", "allowed_paths": ["tests/test_one.py"]}
    shas = iter(["c" * 40, "d" * 40])
    monkeypatch.setattr(loop, "_git_head", lambda: next(shas))

    def fake_popen(cmd, cwd, env, text, start_new_session):
        summary = Path(env["AUTONOMOUS_SUMMARY_PATH"])
        summary.write_text(
            json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "PASS",
                "exit_code": 0,
                "base_sha": "c" * 40,
                "produced_sha": "d" * 40,
                "task_id": "wrong-task",
                "run_nonce": "wrong-nonce",
            }),
            encoding="utf-8",
        )
        return _FakeProcess(env, lambda _: None)

    monkeypatch.setattr(loop.subprocess, "Popen", fake_popen)
    result = loop.run_task(task, 1, tmp_path / "stop", summary_dir=tmp_path)
    assert result["status"] == "FAIL"
    assert result["failure_reason"] == "summary_identity_mismatch"


def test_main_rejects_unverified_multi_task_selector_chain(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        loop,
        "load_tasks",
        lambda: [
            {"id": "t1", "instruction": "one", "allowed_paths": ["tests/test_one.py"]},
            {"id": "t2", "instruction": "two", "allowed_paths": ["tests/test_two.py"]},
        ],
    )
    queue = tmp_path / "queue.json"
    queue.write_text('{"max_tasks_per_run": 3}', encoding="utf-8")
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(
        loop.sys,
        "argv",
        ["loop", "--max-tasks", "2", "--state", str(tmp_path / "loop-state.json"),
         "--results", str(tmp_path / "results.jsonl")],
    )
    assert loop.main() == 80
    results = tmp_path / "results.jsonl"
    assert results.exists()
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "BLOCKED"
    assert rows[0]["task_count"] == 0
    assert rows[0]["exit_code"] == 80
    assert rows[0]["failure_reason"] == "control_tower_multi_task_reselection_unavailable"


def test_main_rejects_queue_limit(monkeypatch, tmp_path: Path):
    queue = tmp_path / "queue.json"
    queue.write_text('{"max_tasks_per_run": 1}', encoding="utf-8")
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop.sys, "argv", ["loop", "--max-tasks", "2", "--state", str(tmp_path / "loop-state.json"), "--results", str(tmp_path / "results.jsonl")])
    try:
        loop.main()
    except SystemExit as exc:
        assert "max_tasks_per_run=1" in str(exc)
    else:
        raise AssertionError("expected queue limit rejection")


def test_produced_head_rejects_rename_from_protected_path_into_allowed_test(monkeypatch):
    monkeypatch.setattr(loop, "_git_head", lambda: "b" * 40)
    calls = []

    def fake_git_checked(*args):
        calls.append(args)
        if args[0] == "merge-base":
            return 0, ""
        if args[:3] == ("diff", "--no-renames", "--name-only"):
            # Git reports both sides of a rename when rename detection is disabled.
            return 0, "core/x.py\ntests/test_y.py"
        raise AssertionError(f"unexpected git command: {args!r}")

    monkeypatch.setattr(loop, "_git_checked", fake_git_checked)
    result = loop._verify_produced_head(
        "a" * 40,
        "b" * 40,
        ["tests/test_y.py"],
    )

    assert result == (False, "diff_outside_allowed_paths")
    assert ("diff", "--no-renames", "--name-only", "a" * 40, "b" * 40) in calls



def test_final_outcome_classifies_success_only_when_all_gates_pass():
    assert loop.classify_final_outcome(
        ["PASS"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        recovery_outcome="success",
    ) == ("COMPLETED", "required_gates_passed")


def test_final_outcome_preserves_explicit_queue_empty_as_not_run():
    assert loop.classify_final_outcome(
        ["NOT_RUN"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        queue_empty=True,
    ) == ("NOT_RUN", "queue_empty")


def test_final_outcome_blocks_held_queue_without_claiming_completion():
    assert loop.classify_final_outcome(
        ["BLOCKED"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        all_tasks_held=True,
    ) == ("BLOCKED", "all_pending_tasks_held")


def test_final_outcome_blocks_held_queue_when_post_run_gate_fails():
    assert loop.classify_final_outcome(
        ["BLOCKED"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="failure",
        sheets_outcome="success",
        all_tasks_held=True,
    ) == ("BLOCKED", "held_queue_post_run_gate_failed:state")


def test_final_outcome_fails_when_task_status_is_not_successful():
    assert loop.classify_final_outcome(
        ["FAIL"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
    ) == ("FAILED", "task_status:FAIL")


def test_final_outcome_fails_when_recovery_persistence_gate_fails():
    assert loop.classify_final_outcome(
        ["PASS"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        recovery_outcome="failure",
    ) == ("FAILED", "post_run_gate_failed:recovery_ai_persistence")


def test_final_outcome_blocks_missing_task_evidence():
    assert loop.classify_final_outcome(
        [],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
    ) == ("BLOCKED", "missing_task_evidence")


def test_final_outcome_queue_empty_blocks_recovery_persistence_failure():
    assert loop.classify_final_outcome(
        ["NOT_RUN"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        recovery_outcome="failure",
        queue_empty=True,
    ) == ("BLOCKED", "queue_empty_post_run_gate_failed:recovery_ai_persistence")


def test_final_outcome_held_queue_blocks_recovery_persistence_failure():
    assert loop.classify_final_outcome(
        ["BLOCKED"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        recovery_outcome="failure",
        all_tasks_held=True,
    ) == ("BLOCKED", "held_queue_post_run_gate_failed:recovery_ai_persistence")

def test_final_outcome_queue_empty_blocks_empty_recovery_persistence_outcome():
    assert loop.classify_final_outcome(
        ["NOT_RUN"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        recovery_outcome="",
        queue_empty=True,
    ) == ("BLOCKED", "queue_empty_post_run_gate_failed:recovery_ai_persistence")


def test_final_outcome_held_queue_blocks_empty_recovery_persistence_outcome():
    assert loop.classify_final_outcome(
        ["BLOCKED"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        recovery_outcome="",
        all_tasks_held=True,
    ) == ("BLOCKED", "held_queue_post_run_gate_failed:recovery_ai_persistence")

def test_distributed_loop_workflow_legacy_label_uses_one_task_limit():
    from pathlib import Path

    workflow = Path(".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert 'elif [ "${EVENT_NAME}" = "pull_request_target" ]; then\n            # Legacy max4 label remains accepted, but runtime safely supports one normal task.\n            expected="1"' in workflow
    assert 'requested="${MAX_TASKS:-1}"' in workflow



def test_rea_block_prevents_minimal_loop_task_execution(monkeypatch, tmp_path: Path):
    from types import SimpleNamespace

    sha = "a" * 40
    task = {
        "id": "rea-block-regression",
        "instruction": "must not execute",
        "allowed_paths": ["tests/test_one.py"],
    }
    queue = tmp_path / "queue.json"
    queue.write_text('{"max_tasks_per_run": 1}', encoding="utf-8")
    results = tmp_path / "results.jsonl"
    state = tmp_path / "loop-state.json"

    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_completed", lambda _path: set())
    monkeypatch.setattr(loop, "load_tasks", lambda: [task])
    monkeypatch.setattr(loop, "_git_head", lambda: sha)
    monkeypatch.setattr(loop, "_load_registered_catalog", lambda _sha: [task])
    monkeypatch.setattr(
        loop.sys,
        "argv",
        [
            "run_minimal_autonomous_loop",
            "--max-tasks",
            "1",
            "--state",
            str(state),
            "--results",
            str(results),
        ],
    )

    from scripts import (
        control_tower_loop_adapter,
        control_tower_loop_observer,
        control_tower_orchestrator,
        rea_control_tower_adapter,
        recovery_ai_loop_adapter,
    )
    from scripts.recovery_ai import RecoveryStore

    monkeypatch.setattr(RecoveryStore, "task_status", lambda self, _task_id: {})
    monkeypatch.setattr(
        "core.control_tower_selector.select_next_task",
        lambda *args, **kwargs: SimpleNamespace(
            next_action="SELECT_REGISTERED_TASK",
            task_template_id=task["id"],
            reason_code="selected",
        ),
    )
    monkeypatch.setattr(
        control_tower_loop_adapter,
        "authorize_registered_task",
        lambda *_args: (True, "authorized"),
    )
    monkeypatch.setattr(
        rea_control_tower_adapter,
        "prepare_rea_evidence",
        lambda _root, expected_sha: {
            "gate": "BLOCKED",
            "reason_code": "test_block",
            "target_sha": expected_sha,
            "execution_authorized": False,
            "patch_authorized": False,
            "hold_clear_authorized": False,
            "merge_deploy_authorized": False,
        },
    )
    monkeypatch.setattr(
        rea_control_tower_adapter,
        "rea_evidence_is_valid_pass",
        lambda *_args, **_kwargs: False,
    )
    persisted = []
    monkeypatch.setattr(
        recovery_ai_loop_adapter,
        "record_loop_outcome",
        lambda _path, result: persisted.append(("recovery", result["status"])) or {"recorded": False, "reason": "preflight_blocked_not_task_failure"},
    )
    monkeypatch.setattr(
        control_tower_loop_observer,
        "record_loop_observation",
        lambda _path, result: persisted.append(("control_tower", result["status"])) or {"recorded": True, "proposal_executable": False},
    )
    monkeypatch.setattr(
        control_tower_orchestrator,
        "coordinate_outcome",
        lambda result: {"phase": "STOP", "next_action": "STOP_AND_REPORT", "reason_code": "rea_blocked", "allow_continue": False, "repair_executed": False},
    )
    monkeypatch.setattr(
        loop,
        "run_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("run_task must not be called when REA is BLOCKED")
        ),
    )

    assert loop.main() == 1
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "BLOCKED"
    assert rows[0]["exit_code"] == 80
    assert rows[0]["failure_reason"] == "control_tower_rea:test_block"
    assert rows[0]["recovery_ai"] == {"recorded": False, "reason": "preflight_blocked_not_task_failure"}
    assert rows[0]["control_tower"]["recorded"] is True
    assert rows[0]["control_tower"]["orchestration"]["allow_continue"] is False
    assert persisted == [("recovery", "BLOCKED"), ("control_tower", "BLOCKED")]


def test_rea_adapter_exception_blocks_minimal_loop_task_execution(monkeypatch, tmp_path: Path):
    from types import SimpleNamespace

    sha = "a" * 40
    task = {
        "id": "rea-block-regression",
        "instruction": "must not execute",
        "allowed_paths": ["tests/test_one.py"],
    }
    queue = tmp_path / "queue.json"
    queue.write_text('{"max_tasks_per_run": 1}', encoding="utf-8")
    results = tmp_path / "results.jsonl"
    state = tmp_path / "loop-state.json"

    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_completed", lambda _path: set())
    monkeypatch.setattr(loop, "load_tasks", lambda: [task])
    monkeypatch.setattr(loop, "_git_head", lambda: sha)
    monkeypatch.setattr(loop, "_load_registered_catalog", lambda _sha: [task])
    monkeypatch.setattr(
        loop.sys,
        "argv",
        [
            "run_minimal_autonomous_loop",
            "--max-tasks",
            "1",
            "--state",
            str(state),
            "--results",
            str(results),
        ],
    )

    from scripts import control_tower_loop_adapter, rea_control_tower_adapter
    from scripts.recovery_ai import RecoveryStore

    monkeypatch.setattr(RecoveryStore, "task_status", lambda self, _task_id: {})
    monkeypatch.setattr(
        "core.control_tower_selector.select_next_task",
        lambda *args, **kwargs: SimpleNamespace(
            next_action="SELECT_REGISTERED_TASK",
            task_template_id=task["id"],
            reason_code="selected",
        ),
    )
    monkeypatch.setattr(
        control_tower_loop_adapter,
        "authorize_registered_task",
        lambda *_args: (True, "authorized"),
    )
    monkeypatch.setattr(
        rea_control_tower_adapter,
        "prepare_rea_evidence",
        lambda _root, expected_sha: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        rea_control_tower_adapter,
        "rea_evidence_is_valid_pass",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        loop,
        "run_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("run_task must not be called when REA is BLOCKED")
        ),
    )

    # The result row keeps the REA-specific exit code, while the shared
    # post-run orchestration path returns its fail-closed process exit code.
    assert loop.main() == 1
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "BLOCKED"
    assert rows[0]["exit_code"] == 80
    assert rows[0]["failure_reason"] == "control_tower_rea:rea_adapter_error"
    assert rows[0]["rea"]["reason_code"] == "rea_adapter_error"
    assert rows[0]["rea"]["execution_authorized"] is False
    # A preflight block is not counted as a task failure, but Control Tower
    # must still persist the BLOCKED observation for auditability.
    assert not (tmp_path / "recovery-ai-state.json").exists()
    assert (tmp_path / "control-tower-observations.jsonl").exists()


def test_authorization_denial_skips_rea_and_clears_task_evidence(monkeypatch, tmp_path: Path):
    from types import SimpleNamespace

    sha = "a" * 40
    task = {
        "id": "rea-block-regression",
        "instruction": "must not execute",
        "allowed_paths": ["tests/test_one.py"],
    }
    queue = tmp_path / "queue.json"
    queue.write_text('{"max_tasks_per_run": 1}', encoding="utf-8")
    results = tmp_path / "results.jsonl"
    state = tmp_path / "loop-state.json"

    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_completed", lambda _path: set())
    monkeypatch.setattr(loop, "load_tasks", lambda: [task])
    monkeypatch.setattr(loop, "_git_head", lambda: sha)
    monkeypatch.setattr(loop, "_load_registered_catalog", lambda _sha: [task])
    monkeypatch.setattr(
        loop.sys,
        "argv",
        [
            "run_minimal_autonomous_loop",
            "--max-tasks",
            "1",
            "--state",
            str(state),
            "--results",
            str(results),
        ],
    )

    from scripts import control_tower_loop_adapter, rea_control_tower_adapter
    from scripts.recovery_ai import RecoveryStore

    monkeypatch.setattr(RecoveryStore, "task_status", lambda self, _task_id: {})
    monkeypatch.setattr(
        "core.control_tower_selector.select_next_task",
        lambda *args, **kwargs: SimpleNamespace(
            next_action="SELECT_REGISTERED_TASK",
            task_template_id=task["id"],
            reason_code="selected",
        ),
    )
    monkeypatch.setattr(
        control_tower_loop_adapter,
        "authorize_registered_task",
        lambda *_args: (False, "authorization_denied"),
    )
    rea_calls = []
    monkeypatch.setattr(
        rea_control_tower_adapter,
        "prepare_rea_evidence",
        lambda _root, expected_sha: rea_calls.append(expected_sha),
    )
    monkeypatch.setattr(
        rea_control_tower_adapter,
        "rea_evidence_is_valid_pass",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        loop,
        "run_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("run_task must not be called when REA is BLOCKED")
        ),
    )

    assert loop.main() == 1
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["failure_reason"] == "control_tower_gate:authorization_denied"
    assert rows[0].get("rea") is None
    assert rea_calls == []
