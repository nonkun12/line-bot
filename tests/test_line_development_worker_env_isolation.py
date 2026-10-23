"""Ensure runtime-only task context does not leak into the full pytest subprocess."""
import os

import pytest

from scripts import line_development_worker_v2 as worker


TASK_SCOPED_NAMES = (
    "AUTONOMOUS_ALLOWED_PATHS",
    "AUTONOMOUS_TASK_ID",
    "AUTONOMOUS_SUMMARY_PATH",
    "AUTONOMOUS_RUN_NONCE",
    "AUTONOMOUS_RUN_SOURCE",
    "DEV_INSTRUCTION",
)


class _Success:
    returncode = 0
    stdout = "1 passed"
    stderr = ""


def test_run_tests_hides_task_context_during_pytest_and_restores_parent(monkeypatch):
    original = {name: f"test-only-{name.lower()}" for name in TASK_SCOPED_NAMES}
    for name, value in original.items():
        monkeypatch.setenv(name, value)

    observed = []

    def fake_run(command, timeout=900, input_text=None, env=None):
        if command[1:4] == ["-m", "pytest", "-q"]:
            observed.append({name: os.environ.get(name) for name in TASK_SCOPED_NAMES})
        return _Success()

    monkeypatch.setattr(worker, "run", fake_run)
    success, output = worker.run_tests()

    assert success is True
    assert "1 passed" in output
    assert observed == [{name: None for name in TASK_SCOPED_NAMES}]
    assert {name: os.environ.get(name) for name in TASK_SCOPED_NAMES} == original


def test_run_tests_restores_task_context_when_pytest_runner_raises(monkeypatch):
    original = {name: f"failure-test-{name.lower()}" for name in TASK_SCOPED_NAMES}
    for name, value in original.items():
        monkeypatch.setenv(name, value)

    def fail_run(command, timeout=900, input_text=None, env=None):
        if command[1:4] == ["-m", "pytest", "-q"]:
            assert all(os.environ.get(name) is None for name in TASK_SCOPED_NAMES)
            raise RuntimeError("simulated pytest launcher failure")
        return _Success()

    monkeypatch.setattr(worker, "run", fail_run)
    with pytest.raises(RuntimeError, match="simulated pytest launcher failure"):
        worker.run_tests()

    assert {name: os.environ.get(name) for name in TASK_SCOPED_NAMES} == original
