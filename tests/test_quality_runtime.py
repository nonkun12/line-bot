from core.multi_agent import AgentResult, AgentRole, AgentTask
from core.quality_runtime import QualityRuntime


class FakeExecutor:
    def __init__(self, outcomes=None):
        self.calls = []
        self.outcomes = list(outcomes or [])

    def execute(self, task):
        self.calls.append(task)
        success = self.outcomes.pop(0) if self.outcomes else True
        return AgentResult(task.task_id, success, "ok" if success else "failed", task.resources)


def base_tasks():
    resources = frozenset({"working-tree"})
    return (
        AgentTask("manager", AgentRole.MANAGER, "select", frozenset({"target"})),
        AgentTask("implementer", AgentRole.IMPLEMENTER, "implement", resources),
        AgentTask("tester", AgentRole.TESTER, "test", resources),
        AgentTask("reviewer", AgentRole.REVIEWER, "review", resources),
        AgentTask("integrator", AgentRole.INTEGRATOR, "integrate", resources),
    )


def test_passing_test_skips_debug_and_refactor():
    executor = FakeExecutor()
    runtime = QualityRuntime({role: executor for role in AgentRole}, max_rounds=3)

    report = runtime.run(base_tasks())

    assert report.success
    assert report.integration_ready
    assert [call.role for call in executor.calls] == [
        AgentRole.MANAGER,
        AgentRole.IMPLEMENTER,
        AgentRole.TESTER,
        AgentRole.REVIEWER,
        AgentRole.INTEGRATOR,
    ]


def test_failed_test_runs_debug_refactor_then_mandatory_retest():
    executor = FakeExecutor([True, True, False, True, True, True])
    runtime = QualityRuntime({role: executor for role in AgentRole}, max_rounds=3)

    report = runtime.run(base_tasks())

    assert report.success
    assert [call.role for call in executor.calls] == [
        AgentRole.MANAGER,
        AgentRole.IMPLEMENTER,
        AgentRole.TESTER,
        AgentRole.DEBUGGER,
        AgentRole.REFACTORER,
        AgentRole.TESTER,
        AgentRole.REVIEWER,
        AgentRole.INTEGRATOR,
    ]
    assert report.repair_attempts == 1


def test_debug_failure_fails_closed_without_refactor():
    executor = FakeExecutor([True, True, False, False])
    runtime = QualityRuntime({role: executor for role in AgentRole}, max_rounds=3)

    report = runtime.run(base_tasks())

    assert not report.success
    assert report.failed_task_id.startswith("debug:")
    assert [call.role for call in executor.calls] == [
        AgentRole.MANAGER,
        AgentRole.IMPLEMENTER,
        AgentRole.TESTER,
        AgentRole.DEBUGGER,
    ]


def test_refactor_failure_fails_closed_without_retest():
    executor = FakeExecutor([True, True, False, True, False])
    runtime = QualityRuntime({role: executor for role in AgentRole}, max_rounds=3)

    report = runtime.run(base_tasks())

    assert not report.success
    assert report.failed_task_id.startswith("refactor:")
    assert [call.role for call in executor.calls] == [
        AgentRole.MANAGER,
        AgentRole.IMPLEMENTER,
        AgentRole.TESTER,
        AgentRole.DEBUGGER,
        AgentRole.REFACTORER,
    ]


def test_failed_retest_is_bounded():
    executor = FakeExecutor([True, True, False, True, True, False, True, True, False])
    runtime = QualityRuntime({role: executor for role in AgentRole}, max_rounds=3)

    report = runtime.run(base_tasks())

    assert not report.success
    assert report.failed_task_id.startswith("test:")
    roles = [call.role for call in executor.calls]
    assert roles.count(AgentRole.DEBUGGER) == 2
    assert roles.count(AgentRole.REFACTORER) == 2
    assert roles.count(AgentRole.TESTER) == 3
    assert AgentRole.REVIEWER not in roles


def test_failed_review_runs_debug_refactor_retest_and_rereview():
    executor = FakeExecutor([True, True, True, False, True, True, True, True])
    runtime = QualityRuntime({role: executor for role in AgentRole}, max_rounds=3)

    report = runtime.run(base_tasks())

    assert report.success
    assert [call.role for call in executor.calls] == [
        AgentRole.MANAGER,
        AgentRole.IMPLEMENTER,
        AgentRole.TESTER,
        AgentRole.REVIEWER,
        AgentRole.DEBUGGER,
        AgentRole.REFACTORER,
        AgentRole.TESTER,
        AgentRole.REVIEWER,
        AgentRole.INTEGRATOR,
    ]


def test_failed_review_debugger_failure_fails_closed():
    executor = FakeExecutor([True, True, True, False, False])
    runtime = QualityRuntime({role: executor for role in AgentRole}, max_rounds=3)

    report = runtime.run(base_tasks())

    assert not report.success
    assert report.failed_task_id.startswith("debug:")
    roles = [call.role for call in executor.calls]
    assert roles.count(AgentRole.DEBUGGER) == 1
    assert AgentRole.REFACTORER not in roles


def test_failed_review_retest_failure_is_reported_and_bounded():
    executor = FakeExecutor([True, True, True, False, True, True, False])
    runtime = QualityRuntime({role: executor for role in AgentRole}, max_rounds=3)

    report = runtime.run(base_tasks())

    assert not report.success
    assert report.failed_task_id.startswith("test:")
    roles = [call.role for call in executor.calls]
    assert roles.count(AgentRole.REVIEWER) == 1
    assert roles.count(AgentRole.DEBUGGER) == 1
    assert roles.count(AgentRole.REFACTORER) == 1
    assert roles.count(AgentRole.TESTER) == 2


def test_repeated_review_failures_stop_at_max_rounds():
    executor = FakeExecutor([True, True, True, False, True, True, True, False, True, True, False])
    runtime = QualityRuntime({role: executor for role in AgentRole}, max_rounds=3)

    report = runtime.run(base_tasks())

    assert not report.success
    assert report.failed_task_id.startswith("review:")
    roles = [call.role for call in executor.calls]
    assert roles.count(AgentRole.REVIEWER) == 3
    assert roles.count(AgentRole.DEBUGGER) == 2
    assert roles.count(AgentRole.REFACTORER) == 2
    assert roles.count(AgentRole.TESTER) == 3
    assert report.repair_attempts == 2
