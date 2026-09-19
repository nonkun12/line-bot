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


def test_scheduler_fails_closed_on_invalid_agent_result_fields() -> None:
    class BadSuccess:
        def execute(self, task: AgentTask) -> AgentResult:
            return AgentResult(task.task_id, "yes", "done")  # type: ignore[arg-type]

    scheduler = DistributedTaskScheduler({AgentRole.TESTER: BadSuccess()})
    with pytest.raises(DistributedExecutionError, match="success must be bool"):
        scheduler.run((task("test", AgentRole.TESTER),))

    class BadResources:
        def execute(self, task: AgentTask) -> AgentResult:
            return AgentResult(task.task_id, True, "done", {"unsafe"})  # type: ignore[arg-type]

    scheduler = DistributedTaskScheduler({AgentRole.TESTER: BadResources()})
    with pytest.raises(DistributedExecutionError, match="changed_resources must be frozenset"):
        scheduler.run((task("test", AgentRole.TESTER),))


def test_scheduler_rejects_empty_task_plan() -> None:
    scheduler = DistributedTaskScheduler({}, max_workers=1)
    with pytest.raises(DistributedExecutionError, match="at least one task is required"):
        scheduler.run(())
