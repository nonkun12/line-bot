import threading
import time

import pytest

from core.agent_runtime import MultiAgentRuntime
from core.multi_agent import AgentResult, AgentRole, AgentTask


class FakeExecutor:
    def __init__(self, *, delay=0.0, fail=False):
        self.delay = delay
        self.fail = fail
        self.started = []
        self.finished = []
        self._lock = threading.Lock()

    def execute(self, task):
        with self._lock:
            self.started.append(task.task_id)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        with self._lock:
            self.finished.append(task.task_id)
        return AgentResult(task_id=task.task_id, success=True, summary="ok")


def task(task_id, role, resources=(), depends_on=()):
    return AgentTask(
        task_id=task_id,
        role=role,
        instruction=f"work on {task_id}",
        resources=frozenset(resources),
        depends_on=tuple(depends_on),
    )


def test_independent_agents_execute_concurrently():
    impl = FakeExecutor(delay=0.05)
    tester = FakeExecutor(delay=0.05)
    runtime = MultiAgentRuntime(
        {AgentRole.IMPLEMENTER: impl, AgentRole.TESTER: tester}, max_workers=2
    )

    started = time.monotonic()
    report = runtime.run(
        [
            task("impl", AgentRole.IMPLEMENTER, {"a.py"}),
            task("test", AgentRole.TESTER, {"b.py"}),
        ]
    )

    assert report.success
    assert [item.task.task_id for item in report.completed] == ["impl", "test"]
    assert time.monotonic() - started < 0.09


def test_dependencies_wait_for_previous_batch():
    impl = FakeExecutor()
    tester = FakeExecutor()
    runtime = MultiAgentRuntime(
        {AgentRole.IMPLEMENTER: impl, AgentRole.TESTER: tester}
    )

    report = runtime.run(
        [
            task("impl", AgentRole.IMPLEMENTER, {"a.py"}),
            task("test", AgentRole.TESTER, {"test_a.py"}, {"impl"}),
        ]
    )

    assert report.success
    assert impl.finished == ["impl"]
    assert tester.started == ["test"]


def test_failure_stops_later_batches():
    failing = FakeExecutor(fail=True)
    later = FakeExecutor()
    runtime = MultiAgentRuntime(
        {AgentRole.IMPLEMENTER: failing, AgentRole.TESTER: later}
    )

    report = runtime.run(
        [
            task("impl", AgentRole.IMPLEMENTER, {"a.py"}),
            task("test", AgentRole.TESTER, {"test_a.py"}, {"impl"}),
        ]
    )

    assert not report.success
    assert report.failed_task_id == "impl"
    assert later.started == []


def test_missing_executor_fails_closed():
    runtime = MultiAgentRuntime({AgentRole.IMPLEMENTER: FakeExecutor()})

    report = runtime.run([task("test", AgentRole.TESTER, {"test_a.py"})])

    assert not report.success
    assert report.failed_task_id == "test"
    assert "missing executor" in report.error


def test_malformed_result_fails_closed():
    class BadExecutor:
        def execute(self, task):
            return AgentResult(task_id="other", success=True)

    runtime = MultiAgentRuntime({AgentRole.TESTER: BadExecutor()})

    report = runtime.run([task("test", AgentRole.TESTER)])

    assert not report.success
    assert report.failed_task_id == "test"
    assert "task_id" in report.error


def test_unsuccessful_agent_result_fails_closed():
    class UnsuccessfulExecutor:
        def execute(self, task):
            return AgentResult(task_id=task.task_id, success=False, summary="tests failed")

    runtime = MultiAgentRuntime({AgentRole.TESTER: UnsuccessfulExecutor()})

    report = runtime.run([task("test", AgentRole.TESTER)])

    assert not report.success
    assert report.failed_task_id == "test"
    assert "tests failed" in report.error


def test_invalid_worker_count_is_rejected():
    with pytest.raises(ValueError, match="max_workers"):
        MultiAgentRuntime({}, max_workers=0)
