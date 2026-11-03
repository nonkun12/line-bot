"""Regression tests for retry safety checks performed after backoff."""
from pathlib import Path

import pytest

from scripts import run_minimal_autonomous_loop as loop


@pytest.mark.parametrize("change", ["stop", "dirty", "head"])
def test_retry_is_blocked_when_safety_state_changes_during_backoff(
    monkeypatch, tmp_path: Path, change: str
):
    sha = "e" * 40
    calls = []
    stops = []
    statuses = []
    heads = []

    def run_task(task, index, stop_file, *, expected_base_sha):
        calls.append(expected_base_sha)
        return {
            "status": "FAIL",
            "failure_reason": "HTTP status=503",
            "base_sha": sha,
            "produced_sha": sha,
        }

    def stopped(_path):
        stops.append(True)
        return change == "stop" and len(stops) > 1

    def git_checked(*args):
        statuses.append(args)
        return (0, "?? changed.txt") if change == "dirty" and len(statuses) > 1 else (0, "")

    def git_head():
        heads.append(True)
        return "f" * 40 if change == "head" and len(heads) > 1 else sha

    monkeypatch.setattr(loop, "run_task", run_task)
    monkeypatch.setattr(loop, "_git_head", git_head)
    monkeypatch.setattr(loop, "_git_checked", git_checked)
    monkeypatch.setattr(loop, "stopped", stopped)
    monkeypatch.setattr(loop.time, "sleep", lambda _seconds: None)

    result, retries = loop.run_task_with_transient_recovery(
        {"id": "backoff-safety-test"}, 1, tmp_path / "stop", expected_base_sha=sha
    )

    assert result["status"] == "FAIL"
    assert retries == 0
    assert calls == [sha]
    assert len(stops) >= 2


def test_retry_count_includes_only_dispatched_retries(monkeypatch, tmp_path: Path):
    sha = "1" * 40
    calls = []
    heads = iter([sha, "2" * 40])

    def run_task(task, index, stop_file, *, expected_base_sha):
        calls.append(expected_base_sha)
        return {
            "status": "FAIL",
            "failure_reason": "HTTP status=503",
            "base_sha": sha,
            "produced_sha": sha,
        }

    monkeypatch.setattr(loop, "run_task", run_task)
    monkeypatch.setattr(loop, "_git_head", lambda: next(heads))
    monkeypatch.setattr(loop, "_git_checked", lambda *args: (0, ""))
    monkeypatch.setattr(loop, "stopped", lambda _path: False)
    monkeypatch.setattr(loop.time, "sleep", lambda _seconds: None)

    _result, retries = loop.run_task_with_transient_recovery(
        {"id": "head-change-test"}, 1, tmp_path / "stop", expected_base_sha=sha
    )

    assert retries == 0
    assert calls == [sha]
