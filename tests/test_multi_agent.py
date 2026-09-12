from core.multi_agent import (
    AgentRole,
    AgentTask,
    default_development_team,
    plan_batches,
    resources_conflict,
)


def task(task_id, role=AgentRole.TESTER, resources=(), depends_on=(), priority=0):
    return AgentTask(
        task_id=task_id,
        role=role,
        instruction=f"work on {task_id}",
        resources=frozenset(resources),
        depends_on=tuple(depends_on),
        priority=priority,
    )


def test_independent_tasks_run_in_parallel():
    batches = plan_batches(
        [
            task("impl", AgentRole.IMPLEMENTER, {"core/a.py"}),
            task("review", AgentRole.REVIEWER, {"core/b.py"}),
        ]
    )

    assert [[item.task_id for item in batch.tasks] for batch in batches] == [["impl", "review"]]


def test_conflicting_tasks_are_serialized():
    batches = plan_batches(
        [
            task("first", resources={"core/shared.py"}),
            task("second", resources={"core/shared.py"}),
        ]
    )

    assert [[item.task_id for item in batch.tasks] for batch in batches] == [["first"], ["second"]]
    assert resources_conflict(batches[0].tasks[0], batches[1].tasks[0])


def test_dependencies_create_ordered_batches():
    batches = plan_batches(
        [
            task("implement", AgentRole.IMPLEMENTER, {"core/a.py"}),
            task("test", AgentRole.TESTER, {"tests/test_a.py"}, {"implement"}),
            task("review", AgentRole.REVIEWER, {"core/a.py", "tests/test_a.py"}, {"test"}),
        ]
    )

    assert [[item.task_id for item in batch.tasks] for batch in batches] == [
        ["implement"],
        ["test"],
        ["review"],
    ]


def test_missing_dependency_fails_closed():
    try:
        plan_batches([task("test", depends_on={"missing"})])
    except ValueError as exc:
        assert "missing dependency" in str(exc)
    else:
        raise AssertionError("missing dependency must fail closed")


def test_cycles_fail_closed():
    tasks = [
        task("a", depends_on={"b"}),
        task("b", depends_on={"a"}),
    ]

    try:
        plan_batches(tasks)
    except ValueError as exc:
        assert "cyclic" in str(exc)
    else:
        raise AssertionError("cycle must fail closed")


def test_default_team_has_all_six_roles():
    assert default_development_team() == (
        AgentRole.MANAGER,
        AgentRole.IMPLEMENTER,
        AgentRole.TESTER,
        AgentRole.REVIEWER,
        AgentRole.REPAIRER,
        AgentRole.INTEGRATOR,
    )
