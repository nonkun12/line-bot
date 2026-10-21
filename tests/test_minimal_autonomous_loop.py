from __future__ import annotations

import pytest

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import run_minimal_autonomous_loop as loop
from scripts.run_minimal_autonomous_loop import load_completed, load_tasks, stopped


@pytest.mark.parametrize("record,blocked", [
    ({}, False),
    ({"held": False}, False),
    ({"held": True}, True),
    ({"held": False, "resume_requires_review": True}, True),
    ({"held": False, "resume_requires_review": False}, False),
])
def test_recovery_review_gate_blocks_only_held_or_unreviewed_resumed_tasks(record, blocked):
    from scripts.run_minimal_autonomous_loop import recovery_record_blocks_task

    assert recovery_record_blocks_task(record) is blocked


@pytest.mark.parametrize("record", [
    {"held": "false"},
    {"resume_requires_review": True},
    {"held": False, "resume_requires_review": "false"},
])
def test_recovery_review_gate_fails_closed_on_ambiguous_state(record):
    from scripts.run_minimal_autonomous_loop import recovery_record_blocks_task

    with pytest.raises(ValueError):
        recovery_record_blocks_task(record)


def test_queue_is_nonempty_and_run_limit_is_bounded():
    queue_data = json.loads(loop.QUEUE.read_text(encoding="utf-8"))
    tasks = load_tasks()
    assert tasks
    assert 1 <= queue_data["max_tasks_per_run"] <= 4
    assert all(task["id"] and task["instruction"] and task["allowed_paths"] for task in tasks)


def test_control_tower_kill_switch_blocks_before_queue_or_task_launch(monkeypatch, tmp_path: Path):
    results = tmp_path / "results.jsonl"
    events = []

    class _Queue:
        def read_text(self, encoding="utf-8"):
            events.append("queue")
            raise AssertionError("queue must not be read while kill switch is enabled")

    monkeypatch.setattr(loop, "QUEUE", _Queue())
    monkeypatch.setattr(loop, "_git_head", lambda: events.append("head") or "a" * 40)
    monkeypatch.setenv("CONTROL_TOWER_KILL_SWITCH", "true")
    monkeypatch.setattr(loop.sys, "argv", ["run_minimal_autonomous_loop", "--results", str(results)])

    assert loop.main() == 80
    assert events == []
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[-1])
    assert row["status"] == "BLOCKED"
    assert row["failure_reason"] == "control_tower_kill_switch_enabled"
    assert row["control_tower"]["orchestration"]["allow_continue"] is False


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


def _write_blocked_summary(env, summary: Path, *, rea: dict[str, object], sha: str) -> None:
    summary.write_text(
        json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "BLOCKED",
            "exit_code": 80,
            "base_sha": sha,
            "produced_sha": sha,
            "task_id": "blocked-summary-test",
            "run_nonce": env["AUTONOMOUS_RUN_NONCE"],
            "failure_reason": "control_tower_rea:test_block",
            "rea": rea,
        }),
        encoding="utf-8",
    )


def test_blocked_summary_requires_authority_denials(monkeypatch, tmp_path: Path):
    task = {"id": "blocked-summary-test", "instruction": "test", "allowed_paths": ["tests/test_one.py"]}
    sha = "a" * 40
    monkeypatch.setattr(loop, "_git_head", lambda: sha)

    def fake_popen(cmd, cwd, env, text, start_new_session):
        summary = Path(env["AUTONOMOUS_SUMMARY_PATH"])
        _write_blocked_summary(env, summary, rea={
            "gate": "BLOCKED",
            "reason_code": "test_block",
            "execution_authorized": True,
            "patch_authorized": False,
            "hold_clear_authorized": False,
            "merge_deploy_authorized": False,
        }, sha=sha)
        return _FakeProcess(env, lambda _: None, returncode=80)

    monkeypatch.setattr(loop.subprocess, "Popen", fake_popen)
    result = loop.run_task(task, 1, tmp_path / "stop", summary_dir=tmp_path)
    assert result["status"] == "FAIL"
    assert result["failure_reason"] == "blocked_summary_rea_evidence_invalid"


def test_valid_blocked_summary_remains_blocked(monkeypatch, tmp_path: Path):
    task = {"id": "blocked-summary-test", "instruction": "test", "allowed_paths": ["tests/test_one.py"]}
    sha = "a" * 40
    monkeypatch.setattr(loop, "_git_head", lambda: sha)

    def fake_popen(cmd, cwd, env, text, start_new_session):
        summary = Path(env["AUTONOMOUS_SUMMARY_PATH"])
        _write_blocked_summary(env, summary, rea={
            "gate": "BLOCKED",
            "reason_code": "test_block",
            "execution_authorized": False,
            "patch_authorized": False,
            "hold_clear_authorized": False,
            "merge_deploy_authorized": False,
        }, sha=sha)
        return _FakeProcess(env, lambda _: None, returncode=80)

    monkeypatch.setattr(loop.subprocess, "Popen", fake_popen)
    result = loop.run_task(task, 1, tmp_path / "stop", summary_dir=tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["exit_code"] == 80
    assert result["failure_reason"] == "control_tower_rea:test_block"
    assert result["rea"]["execution_authorized"] is False


def test_blocked_summary_failure_reason_must_match_rea_evidence(monkeypatch, tmp_path: Path):
    task = {"id": "blocked-summary-test", "instruction": "test", "allowed_paths": ["tests/test_one.py"]}
    sha = "a" * 40
    monkeypatch.setattr(loop, "_git_head", lambda: sha)

    def fake_popen(cmd, cwd, env, text, start_new_session):
        summary = Path(env["AUTONOMOUS_SUMMARY_PATH"])
        _write_blocked_summary(env, summary, rea={
            "gate": "BLOCKED",
            "reason_code": "test_block",
            "execution_authorized": False,
            "patch_authorized": False,
            "hold_clear_authorized": False,
            "merge_deploy_authorized": False,
        }, sha=sha)
        payload = json.loads(summary.read_text(encoding="utf-8"))
        payload["failure_reason"] = ""
        summary.write_text(json.dumps(payload), encoding="utf-8")
        return _FakeProcess(env, lambda _: None, returncode=80)

    monkeypatch.setattr(loop.subprocess, "Popen", fake_popen)
    result = loop.run_task(task, 1, tmp_path / "stop", summary_dir=tmp_path)
    assert result["status"] == "FAIL"
    assert result["failure_reason"] == "blocked_summary_failure_reason_invalid"


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


def test_reselection_uses_fresh_head_and_registered_definition():
    queued = [
        {"id": "t1", "instruction": "one", "allowed_paths": ["tests/test_one.py"]},
        {"id": "t2", "instruction": "two", "allowed_paths": ["tests/test_two.py"]},
    ]
    selected, reason = loop.reselect_registered_task(
        queued,
        list(queued),
        {"t1"},
        set(),
        expected_task_id="t2",
        evidence_sha="b" * 40,
        current_head_sha="b" * 40,
    )
    assert selected == queued[1]
    assert reason == ""


def test_reselection_blocks_when_head_changes_between_tasks():
    queued = [{"id": "t2", "instruction": "two", "allowed_paths": ["tests/test_two.py"]}]
    selected, reason = loop.reselect_registered_task(
        queued, list(queued), set(), set(),
        expected_task_id="t2",
        evidence_sha="b" * 40,
        current_head_sha="c" * 40,
    )
    assert selected is None
    assert reason == "policy_blocked"


def test_reselection_blocks_if_recovery_hold_appears_between_tasks():
    queued = [{"id": "t2", "instruction": "two", "allowed_paths": ["tests/test_two.py"]}]
    selected, reason = loop.reselect_registered_task(
        queued, list(queued), set(), {"t2"},
        expected_task_id="t2",
        evidence_sha="b" * 40,
        current_head_sha="b" * 40,
    )
    assert selected is None
    assert reason == "task_held"


def test_reselection_blocks_if_queue_definition_differs_from_catalog():
    queued = [{"id": "t2", "instruction": "unreviewed", "allowed_paths": ["tests/test_two.py"]}]
    catalog = [{"id": "t2", "instruction": "reviewed", "allowed_paths": ["tests/test_two.py"]}]
    selected, reason = loop.reselect_registered_task(
        queued, catalog, set(), set(),
        expected_task_id="t2",
        evidence_sha="b" * 40,
        current_head_sha="b" * 40,
    )
    assert selected is None
    assert reason == "definition_mismatch"

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

def test_distributed_loop_workflow_owner_max4_label_uses_four_task_limit():
    from pathlib import Path

    workflow = Path(".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert 'elif [ "${EVENT_NAME}" = "pull_request_target" ]; then\n            # The owner-only distributed-loop-max4 label requests a bounded four-task run.\n            expected="4"' in workflow
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


def test_orchestrator_gates_successful_loop_on_exact_evidence(monkeypatch, tmp_path: Path):
    from types import SimpleNamespace

    from scripts import (
        control_tower_loop_adapter,
        control_tower_loop_observer,
        rea_control_tower_adapter,
        recovery_ai_loop_adapter,
    )
    from scripts.recovery_ai import RecoveryStore

    sha = "a" * 40
    nonce = "c" * 32
    task = {
        "id": "integration-success",
        "instruction": "test-only integration fixture",
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
    rea = {
        "gate": "PASS",
        "mode": "OBSERVE_ONLY",
        "target_sha": sha,
        "critical_count": 0,
        "blocking_count": 0,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
        "scanner_status": "PASS",
        "finding_count": 0,
        "findings_truncated": False,
        "findings": [],
    }
    monkeypatch.setattr(
        rea_control_tower_adapter,
        "prepare_rea_evidence",
        lambda _root, expected_sha: {**rea, "target_sha": expected_sha},
    )
    monkeypatch.setattr(
        loop,
        "run_task",
        lambda *_args, **_kwargs: {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_index": 1,
            "task_id": task["id"],
            "run_nonce": nonce,
            "status": "NO_CHANGE",
            "exit_code": 0,
            "base_sha": sha,
            "produced_sha": sha,
            "failure_reason": "no_change",
        },
    )
    recovery_evidence = {
        "task_id": task["id"],
        "base_sha": sha,
        "produced_sha": sha,
        "run_nonce": nonce,
    }
    monkeypatch.setattr(
        recovery_ai_loop_adapter,
        "record_loop_outcome",
        lambda _path, result: {
            "recorded": True,
            "verified": True,
            "status": result["status"],
            "evidence": recovery_evidence,
        },
    )
    monkeypatch.setattr(
        control_tower_loop_observer,
        "record_loop_observation",
        lambda _path, result: {
            "recorded": True,
            "observed_status": result["status"],
            "proposal_executable": False,
        },
    )

    assert loop.main() == 0
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["rea"] == rea
    assert rows[0]["recovery_ai"]["evidence"] == recovery_evidence
    assert rows[0]["control_tower"]["orchestration"]["reason_code"] == "verified_success"
    assert rows[0]["control_tower"]["orchestration"]["allow_continue"] is True



def test_registered_catalog_never_trusts_queue_entries(monkeypatch):
    sha = "a" * 40
    queue_only_id = "queue-only-unreviewed-task"
    reviewed_id = "reviewed-catalog-task"
    catalog = {
        "version": 1,
        "tasks": [{
            "id": reviewed_id,
            "instruction": "Use dummy data and change one test only.",
            "allowed_paths": ["tests/test_example.py"],
        }],
    }
    calls = []

    def fake_git_checked(*args):
        calls.append(args)
        assert args[0] == "show"
        assert args[1] == f"{sha}:.github/autonomous-loop-task-catalog.json"
        return 0, json.dumps(catalog)

    monkeypatch.setattr(loop, "_git_checked", fake_git_checked)
    registered = loop._load_registered_catalog(sha)

    assert [task["id"] for task in registered] == [reviewed_id]
    assert queue_only_id not in {task["id"] for task in registered}
    assert len(calls) == 1



def test_registered_catalog_expands_only_reviewed_test_only_refill_policy(monkeypatch, tmp_path: Path):
    sha = "b" * 40
    target = tmp_path / "tests" / "test_auto_target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_placeholder():\\n    assert True\\n", encoding="utf-8")
    catalog = {
        "version": 1,
        "max_additions_per_run": 4,
        "auto_test_refill": {
            "enabled": True,
            "max_tasks_per_run": 1,
            "allowed_roots": ["tests", "uhip/tests"],
        },
        "tasks": [{
            "id": "reviewed-catalog-task",
            "instruction": "Use dummy data and change one test only.",
            "allowed_paths": ["tests/test_example.py"],
        }],
    }

    def fake_git_checked(*args):
        assert args == ("show", f"{sha}:.github/autonomous-loop-task-catalog.json")
        return 0, json.dumps(catalog)

    monkeypatch.setattr(loop, "ROOT", tmp_path)
    monkeypatch.setattr(loop, "_git_checked", fake_git_checked)
    registered = loop._load_registered_catalog(sha)

    from scripts.autonomous_task_proposals import build_auto_test_catalog
    expected = build_auto_test_catalog(tmp_path)
    generated = [item for item in registered if item["id"].startswith("auto-test-")]
    assert generated == expected
    assert len(generated) == 1
    assert generated[0]["allowed_paths"] == ["tests/test_auto_target.py"]


def test_registered_catalog_rejects_broadened_auto_test_policy(monkeypatch):
    sha = "c" * 40
    catalog = {
        "version": 1,
        "auto_test_refill": {
            "enabled": True,
            "max_tasks_per_run": 4,
            "allowed_roots": ["."],
        },
        "tasks": [],
    }

    monkeypatch.setattr(
        loop,
        "_git_checked",
        lambda *_args: (0, json.dumps(catalog)),
    )
    with pytest.raises(ValueError, match="auto test refill policy is invalid"):
        loop._load_registered_catalog(sha)



def test_reselection_preserves_hold_across_auto_task_fingerprint_change():
    queued = [{
        "id": "auto-test-tests-test-example-abcdef123456",
        "instruction": "current fingerprint task",
        "allowed_paths": ["tests/test_example.py"],
    }]
    old_held_id = "auto-test-tests-test-example-deadbeef1234"

    selected, reason = loop.reselect_registered_task(
        queued,
        list(queued),
        set(),
        {old_held_id},
        expected_task_id=queued[0]["id"],
        evidence_sha="b" * 40,
        current_head_sha="b" * 40,
    )

    assert selected is None
    assert reason == "task_held"



def test_load_held_task_ids_includes_records_absent_from_current_queue():
    class FakeRecoveryStore:
        def _read(self):
            return {
                "schema_version": 1,
                "tasks": {
                    "auto-test-tests-test-example-deadbeef1234": {"held": True},
                    "other-resumed-task": {"held": False, "resume_requires_review": True},
                    "normal-task": {"held": False, "resume_requires_review": False},
                },
                "checkpoint": None,
            }

    assert loop.load_held_task_ids(FakeRecoveryStore()) == {
        "auto-test-tests-test-example-deadbeef1234",
        "other-resumed-task",
    }


def test_load_held_task_ids_fails_closed_on_malformed_nonqueued_record():
    class FakeRecoveryStore:
        def _read(self):
            return {
                "schema_version": 1,
                "tasks": {"old-task": {"held": "unknown"}},
                "checkpoint": None,
            }

    with pytest.raises(ValueError, match="recovery hold state is ambiguous"):
        loop.load_held_task_ids(FakeRecoveryStore())



@pytest.mark.parametrize(
    "policy",
    [
        {"enabled": 1, "max_tasks_per_run": 1, "allowed_roots": ["tests", "uhip/tests"]},
        {"enabled": True, "max_tasks_per_run": True, "allowed_roots": ["tests", "uhip/tests"]},
    ],
)
def test_registered_catalog_rejects_boolean_policy_values(monkeypatch, policy):
    sha = "d" * 40
    catalog = {"version": 1, "auto_test_refill": policy, "tasks": []}
    monkeypatch.setattr(loop, "_git_checked", lambda *_args: (0, json.dumps(catalog)))

    with pytest.raises(ValueError, match="auto test refill policy is invalid"):
        loop._load_registered_catalog(sha)
