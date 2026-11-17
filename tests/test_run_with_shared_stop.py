from __future__ import annotations

import subprocess
from unittest.mock import patch

from scripts import run_with_shared_stop as watchdog


class _FakeProcess:
    pid = 4321

    def __init__(self, exit_code=0):
        self.returncode = None
        self.exit_code = exit_code
        self.wait_calls = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.returncode is None:
            self.returncode = self.exit_code
        return self.returncode


def test_blocks_before_spawn_when_shared_stop_is_active():
    with patch.object(watchdog, "get_status", return_value=True), patch.object(
        watchdog.subprocess, "Popen", side_effect=AssertionError("must not spawn")
    ):
        assert watchdog.run_with_shared_stop(["python", "-c", "pass"], repository="o/r", token="t") == 82


def test_blocks_before_spawn_when_shared_stop_is_unverifiable():
    with patch.object(watchdog, "get_status", side_effect=RuntimeError("network")), patch.object(
        watchdog.subprocess, "Popen", side_effect=AssertionError("must not spawn")
    ):
        assert watchdog.run_with_shared_stop(["python", "-c", "pass"], repository="o/r", token="t") == 82


def test_terminates_child_process_group_when_stop_activates():
    process = _FakeProcess(exit_code=-15)
    with patch.object(watchdog, "get_status", side_effect=[False, True]), patch.object(
        watchdog.subprocess, "Popen", return_value=process
    ), patch.object(watchdog.os, "killpg") as killpg, patch.object(watchdog.time, "sleep"):
        assert watchdog.run_with_shared_stop(["python", "-c", "pass"], repository="o/r", token="t") == 82
    killpg.assert_called_once_with(process.pid, watchdog.signal.SIGTERM)
    assert process.wait_calls == 1


def test_returns_child_exit_code_when_stop_stays_inactive():
    process = _FakeProcess(exit_code=7)
    polls = iter([None, 7])
    process.poll = lambda: next(polls)
    with patch.object(watchdog, "get_status", return_value=False), patch.object(
        watchdog.subprocess, "Popen", return_value=process
    ), patch.object(watchdog.time, "sleep"):
        assert watchdog.run_with_shared_stop(["python", "-c", "pass"], repository="o/r", token="t") == 7
