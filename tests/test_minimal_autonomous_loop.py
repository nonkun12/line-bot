from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts import run_minimal_autonomous_loop as loop
from scripts.run_minimal_autonomous_loop import load_completed, load_tasks, stopped


def _valid_test_evidence(run_nonce: str) -> dict:
    return {
        "schema_version": 1,
        "runner": "scripts/line_development_worker_v2.py::run_tests",
        "run_nonce": run_nonce,
        "pytest_command": [sys.executable, "-m", "pytest", "-q", "--tb=native"],
        "pytest_exit_code": 0,
        "pytest_output_sha256": "a" * 64,
        "py_compile": [],
    }


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
                "test_evidence": _valid_test_evidence(env["AUTONOMOUS_RUN_NONCE"]),
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
                "test_evidence": _valid_test_evidence(env["AUTONOMOUS_RUN_NONCE"]),
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




def test_no_change_without_current_run_test_evidence_is_rejected(monkeypatch, tmp_path: Path):
    task = {"id": "no-evidence-test", "instruction": "test", "allowed_paths": ["tests/test_one.py"]}
    sha = "f" * 40
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
    assert result["status"] == "FAIL"
    assert result["failure_reason"] == "summary_test_evidence_missing_or_invalid"


def test_stale_test_evidence_nonce_is_rejected(monkeypatch, tmp_path: Path):
    task = {"id": "stale-evidence-test", "instruction": "test", "allowed_paths": ["tests/test_one.py"]}
    sha = "f" * 40
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
                "test_evidence": _valid_test_evidence("0" * 32),
            }),
            encoding="utf-8",
        )
        return _FakeProcess(env, lambda _: None)

    monkeypatch.setattr(loop.subprocess, "Popen", fake_popen)
    result = loop.run_task(task, 1, tmp_path / "stop", summary_dir=tmp_path)
    assert result["status"] == "FAIL"
    assert result["failure_reason"] == "summary_test_evidence_missing_or_invalid"

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
    monkeypatch.setattr(loop.sys, "argv", ["loop", "--max-tasks", "2", "--results", str(tmp_path / "results.jsonl")])
    assert loop.main() == 1
    lines = (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["task_id"] == "t1"


def test_main_rejects_queue_limit(monkeypatch, tmp_path: Path):
    queue = tmp_path / "queue.json"
    queue.write_text('{"max_tasks_per_run": 1}', encoding="utf-8")
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop.sys, "argv", ["loop", "--max-tasks", "2", "--results", str(tmp_path / "results.jsonl")])
    try:
        loop.main()
    except SystemExit as exc:
        assert "max_tasks_per_run=1" in str(exc)
    else:
        raise AssertionError("expected queue limit rejection")
