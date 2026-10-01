from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.run_minimal_autonomous_loop import load_tasks, stopped


def test_queue_contains_bounded_tasks():
    tasks = load_tasks()
    assert tasks
    assert len(tasks) <= 3
    assert all(task["id"] and task["instruction"] for task in tasks)


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
