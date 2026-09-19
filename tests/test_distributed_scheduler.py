import threading
import time

import pytest

from core.distributed_scheduler import DistributedExecutionError, DistributedTaskScheduler
from core.multi_agent import AgentResult, AgentRole, AgentTask


class RecordingExecutor:
    def __init__(self, role: AgentRole, *, delay: float = 0.0) -> None:
        self.role = role
        self.delay = delay
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def execute(self, task: AgentTask) -> AgentResult:
        with self._lock:
            self.calls.append(task.task_id)
        if self.delay:
            time.sleep(self.delay)
        return AgentResult(task.task_id, True, f"{self.role.value} completed")


def task(task_id: str, role: AgentRole, *, resources=(), depends_on=(), priority=0) -> AgentTask:
    return AgentTask(
        task_id=task_id,
        role=role,
        instruction=task_id,
        resources=frozenset(resources),
        depends_on=tuple(depends_on),
        priority=priority,
    )


def test_scheduler_reuses_dependency_and_resource_batching() -> None:
    manager = RecordingExecutor(AgentRole.MANAGER)
    tester = RecordingExecutor(AgentRole.TESTER)
    scheduler = DistributedTaskScheduler(
        {AgentRole.MANAGER: manager, AgentRole.TESTER: tester}, max_workers=2
    )
    tasks = (
        task("a", AgentRole.MANAGER, resources=("a.py",)),
        task("b", AgentRole.TESTER, resources=("b.py",)),
        task("c", AgentRole.TESTER, resources=("a.py",), depends_on=("a",)),
    )

    run = scheduler.run(tasks)

    assert run.success
    assert [[item.task_id for item in batch.tasks] for batch in run.batches] == [["a", "b"], ["c"]]
    assert [result.task_id for result in run.results] == ["a", "b", "c"]


def test_scheduler_executes_independent_tasks_concurrently_when_explicitly_enabled() -> None:
    first = RecordingExecutor(AgentRole.MANAGER, delay=0.08)
    second = RecordingExecutor(AgentRole.TESTER, delay=0.08)
    scheduler = DistributedTaskScheduler(
        {AgentRole.MANAGER: first, AgentRole.TESTER: second}, max_workers=2
    )
    tasks = (
        task("a", AgentRole.MANAGER, resources=("a.py",)),
        task("b", AgentRole.TESTER, resources=("b.py",)),
    )

    started = time.perf_counter()
    run = scheduler.run(tasks)
    elapsed = time.perf_counter() - started

    assert run.success
    assert elapsed < 0.14
    assert first.calls == ["a"]
    assert second.calls == ["b"]


def test_scheduler_fails_closed_on_missing_executor() -> None:
    scheduler = DistributedTaskScheduler({AgentRole.MANAGER: RecordingExecutor(AgentRole.MANAGER)})

    with pytest.raises(DistributedExecutionError, match="missing executor"):
        scheduler.run((task("test", AgentRole.TESTER),))


def test_scheduler_fails_closed_on_invalid_executor_result() -> None:
    class BadExecutor:
        def execute(self, task: AgentTask):
            return object()

    scheduler = DistributedTaskScheduler({AgentRole.TESTER: BadExecutor()})

    with pytest.raises(DistributedExecutionError, match="AgentResult"):
        scheduler.run((task("test", AgentRole.TESTER),))


def test_scheduler_rejects_invalid_worker_bound() -> None:
    with pytest.raises(ValueError, match="max_workers"):
        DistributedTaskScheduler({}, max_workers=0)


def test_agent_task_rejects_oversized_or_invalid_fields() -> None:
    with pytest.raises(ValueError, match="task_id exceeds"):
        AgentTask("x" * 201, AgentRole.TESTER, "test")

    with pytest.raises(ValueError, match="instruction exceeds"):
        AgentTask("test", AgentRole.TESTER, "x" * 4001)

    with pytest.raises(ValueError, match="too many resources"):
        AgentTask(
            "test",
            AgentRole.TESTER,
            "test",
            resources=frozenset(f"r{i}" for i in range(9)),
        )

    with pytest.raises(ValueError, match="too many dependencies"):
        AgentTask(
            "test",
            AgentRole.TESTER,
            "test",
            depends_on=tuple(f"d{i}" for i in range(9)),
        )

    with pytest.raises(ValueError, match="role must be an AgentRole"):
        AgentTask("test", "tester", "test")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="priority must be an integer"):
        AgentTask("test", AgentRole.TESTER, "test", priority=True)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="between -10 and 10"):
        AgentTask("test", AgentRole.TESTER, "test", priority=11)
