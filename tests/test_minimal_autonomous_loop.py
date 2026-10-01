from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import run_minimal_autonomous_loop as loop
from scripts.run_minimal_autonomous_loop import load_tasks, stopped


def test_queue_contains_bounded_tasks():
    tasks = load_tasks()
    assert tasks
    assert len(tasks) <= 3
    assert all(task["id"] and task["instruction"] and task["allowed_paths"] for task in tasks)


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
