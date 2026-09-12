from __future__ import annotations

import pytest

from core.multi_agent import AgentRole, AgentTask, plan_batches, resources_conflict


def task(task_id: str, resources: frozenset[str] = frozenset(), deps: tuple[str, ...] = ()) -> AgentTask:
    return AgentTask(
        task_id=task_id,
        role=AgentRole.IMPLEMENTER,
        instruction=task_id,
        resources=resources,
        depends_on=deps,
    )


def test_independent_non_conflicting_tasks_share_a_batch() -> None:
    batches = plan_batches([
        task("a", frozenset({"src/a.py"})),
        task("b", frozenset({"src/b.py"})),
    ])
    assert [[item.task_id for item in batch.tasks] for batch in batches] == [["a", "b"]]


def test_resource_conflict_serializes_tasks() -> None:
    left = task("a", frozenset({"src/shared.py"}))
    right = task("b", frozenset({"src/shared.py"}))
    assert resources_conflict(left, right)
    batches = plan_batches([left, right])
    assert [[item.task_id for item in batch.tasks] for batch in batches] == [["a"], ["b"]]


def test_dependencies_force_later_batch() -> None:
    batches = plan_batches([
        task("test", frozenset({"tests/test_a.py"}), ("implement",)),
        task("implement", frozenset({"src/a.py"})),
    ])
    assert [[item.task_id for item in batch.tasks] for batch in batches] == [["implement"], ["test"]]


@pytest.mark.parametrize(
    ("tasks", "message"),
    [
        ([task("same"), task("same")], "duplicate task_id"),
        ([task("test", deps=("missing",))], "missing dependency"),
        ([task("a", deps=("b",)), task("b", deps=("a",))], "cyclic task dependencies"),
    ],
)
def test_invalid_schedules_fail_closed(tasks: list[AgentTask], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        plan_batches(tasks)
