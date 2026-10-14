from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import run_minimal_autonomous_loop as loop
from scripts.run_minimal_autonomous_loop import load_completed, load_tasks, stopped


def test_queue_contains_bounded_tasks():
    tasks = load_tasks()
    assert tasks
    assert len(tasks) <= 4
    assert all(task["id"] and task["instruction"] and task["allowed_paths"] for task in tasks)


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


def test_main_halts_after_first_failure(monkeypatch, tmp_path: Path):
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
        loop,
        "run_task",
        lambda task, index, stop_file: {
            "task_id": task["id"],
            "status": "FAIL",
            "exit_code": 1,
        },
    )
    monkeypatch.setattr(loop.sys, "argv", ["loop", "--max-tasks", "2", "--state", str(tmp_path / "loop-state.json"), "--results", str(tmp_path / "results.jsonl")])
    assert loop.main() == 1
    lines = (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["task_id"] == "t1"


def test_loop_budget_prevents_starting_task_without_30_minutes_remaining(monkeypatch, tmp_path: Path):
    task = {"id": "budget-task", "instruction": "bounded", "allowed_paths": ["tests/test_budget.py"]}
    queue = tmp_path / "queue.json"
    queue.write_text('{"max_tasks_per_run": 1}', encoding="utf-8")
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_tasks", lambda: [task])
    monkeypatch.setenv("AUTONOMOUS_LOOP_BUDGET_SECONDS", "100")
    monkeypatch.setattr(loop, "run_task", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("task must not start")))
    results = tmp_path / "results.jsonl"
    monkeypatch.setattr(loop.sys, "argv", [
        "loop", "--max-tasks", "1", "--state", str(tmp_path / "state.json"),
        "--results", str(results),
    ])

    assert loop.main() == 80
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "BUDGET_EXHAUSTED"
    assert rows[0]["failure_reason"] == "loop_budget_insufficient_for_task"


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


def test_resume_held_task_requires_queue_membership_and_explicit_confirmation(tmp_path: Path):
    from scripts.recovery_ai import RecoveryStore

    store = RecoveryStore(tmp_path / "recovery-ai-state.json")
    for _ in range(3):
        decision = store.record_failure("task-a", "timeout")
    assert decision.action == "HOLD"

    task = {"id": "task-a", "instruction": "bounded task", "allowed_paths": ["tests/test_one.py"]}
    assert loop.resume_held_task_for_run(
        "task-a", cause_fixed=True, queued_tasks=[task], completed=set(), recovery_store=store
    ) == "task-a"
    assert store.task_status("task-a")["held"] is False
    assert store.task_status("task-a")["resume_requires_review"] is True


def test_resume_held_task_rejects_missing_confirmation_unknown_or_completed_task(tmp_path: Path):
    import pytest
    from scripts.recovery_ai import RecoveryStore

    store = RecoveryStore(tmp_path / "recovery-ai-state.json")
    task = {"id": "task-a", "instruction": "bounded task", "allowed_paths": ["tests/test_one.py"]}
    store.record_failure("task-a", "timeout")
    with pytest.raises(ValueError, match="confirmation"):
        loop.resume_held_task_for_run(
            "task-a", cause_fixed=False, queued_tasks=[task], completed=set(), recovery_store=store
        )
    with pytest.raises(ValueError, match="current queue"):
        loop.resume_held_task_for_run(
            "not-queued", cause_fixed=True, queued_tasks=[task], completed=set(), recovery_store=store
        )
    with pytest.raises(ValueError, match="completed"):
        loop.resume_held_task_for_run(
            "task-a", cause_fixed=True, queued_tasks=[task], completed={"task-a"}, recovery_store=store
        )


def test_resume_held_task_for_run_rejects_task_that_is_not_held(tmp_path: Path):
    import pytest
    from scripts.recovery_ai import RecoveryStore

    store = RecoveryStore(tmp_path / "recovery-ai-state.json")
    task = {"id": "task-a", "instruction": "bounded task", "allowed_paths": ["tests/test_one.py"]}
    store.record_failure("task-a", "timeout")
    before = store.task_status("task-a")
    with pytest.raises(ValueError, match="not held"):
        loop.resume_held_task_for_run(
            "task-a", cause_fixed=True, queued_tasks=[task], completed=set(), recovery_store=store
        )
    assert store.task_status("task-a") == before


def test_main_rejects_confirmation_without_task_id_and_incident_mode(monkeypatch, tmp_path: Path):
    import pytest

    queue = tmp_path / "queue.json"
    queue.write_text('{"max_tasks_per_run": 3}', encoding="utf-8")
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_tasks", lambda: [
        {"id": "task-a", "instruction": "bounded task", "allowed_paths": ["tests/test_one.py"]},
    ])
    base = ["loop", "--max-tasks", "1", "--state", str(tmp_path / "loop-state.json"),
            "--results", str(tmp_path / "results.jsonl")]
    monkeypatch.setattr(loop.sys, "argv", base + ["--confirm-cause-fixed"])
    with pytest.raises(SystemExit, match="held-task resume rejected"):
        loop.main()
    monkeypatch.setattr(loop.sys, "argv", base + ["--max-tasks", "2", "--resume-task-id", "task-a",
                                                  "--confirm-cause-fixed", "--incident-category", "local_job_failed",
                                                  "--incident-detail", "OSError"])
    with pytest.raises(SystemExit, match="held-task resume is unavailable in incident mode"):
        loop.main()
    assert not (tmp_path / "results.jsonl").exists()


def test_bounded_repair_requires_timeout_unchanged_sha_and_recovery_approval():
    sha = "a" * 40
    result = {
        "status": "TIMEOUT",
        "failure_reason": "task_timeout",
        "base_sha": sha,
        "produced_sha": sha,
    }
    assert loop.should_attempt_bounded_repair(result, {"action": "REPAIR_ONCE"}, stop_requested=False)
    assert not loop.should_attempt_bounded_repair(result, {"action": "HOLD"}, stop_requested=False)
    assert not loop.should_attempt_bounded_repair({**result, "produced_sha": "b" * 40}, {"action": "REPAIR_ONCE"}, stop_requested=False)
    assert not loop.should_attempt_bounded_repair(result, {"action": "REPAIR_ONCE"}, stop_requested=True)
    assert not loop.should_attempt_bounded_repair({**result, "failure_reason": "security_violation"}, {"action": "REPAIR_ONCE"}, stop_requested=False)


def test_bounded_repair_task_preserves_allowlist_and_rejects_other_reasons():
    import pytest

    task = {
        "id": "task-a",
        "instruction": "Fix the bounded task.",
        "allowed_paths": ["tests/test_one.py"],
    }
    repaired = loop.build_bounded_repair_task(task, "task_timeout")
    assert repaired["allowed_paths"] == task["allowed_paths"]
    assert "attempt (1 of 1)" in repaired["instruction"]
    assert "\n\nRecovery AI automatic repair attempt" in repaired["instruction"]
    with pytest.raises(ValueError, match="not allowlisted"):
        loop.build_bounded_repair_task(task, "security_violation")
