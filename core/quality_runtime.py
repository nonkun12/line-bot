"""Bounded quality pipeline with distinct TEST, Debug, and Refactor roles."""
from __future__ import annotations

from typing import Mapping, Sequence

from .agent_runtime import RuntimeReport, RuntimeTaskResult
from .multi_agent import AgentResult, AgentRole, AgentTask


class QualityRuntime:
    """Run quality gates with explicit, bounded repair budgets per gate.

    ``max_rounds`` is the maximum number of rounds for each quality gate.
    Thus ``max_rounds=3`` permits the original attempt plus at most two
    Debugger -> Refactorer -> Retest cycles for TEST and independently for
    REVIEW. ``max_rounds=1`` intentionally disables repair retries.
    """

    def __init__(self, executors: Mapping[AgentRole, object], *, max_rounds: int = 3) -> None:
        if max_rounds < 1 or max_rounds > 3:
            raise ValueError("max_rounds must be between 1 and 3")
        self._executors = dict(executors)
        self._max_rounds = max_rounds

    def _execute(self, task: AgentTask) -> RuntimeTaskResult:
        executor = self._executors.get(task.role)
        if executor is None:
            return RuntimeTaskResult(
                task,
                AgentResult(task.task_id, False, f"missing executor for role: {task.role.value}"),
            )
        try:
            result = executor.execute(task)
        except Exception as exc:
            result = AgentResult(task.task_id, False, f"{type(exc).__name__}: {exc}")
        if not isinstance(result, AgentResult):
            result = AgentResult(task.task_id, False, "executor must return AgentResult")
        elif result.task_id != task.task_id:
            result = AgentResult(task.task_id, False, f"executor returned task_id {result.task_id!r}")
        return RuntimeTaskResult(task, result)

    def _quality_repair(
        self,
        failed: RuntimeTaskResult,
        attempt: int,
        completed: list[RuntimeTaskResult],
    ) -> RuntimeTaskResult | None:
        if AgentRole.DEBUGGER not in self._executors or AgentRole.REFACTORER not in self._executors:
            return None

        debug = AgentTask(
            f"debug:{attempt}:{failed.task.task_id}",
            AgentRole.DEBUGGER,
            f"Analyze and fix the failure from {failed.task.task_id}: {failed.result.summary[-2000:]}",
            failed.task.resources,
        )
        debug_result = self._execute(debug)
        completed.append(debug_result)
        if not debug_result.result.success:
            return debug_result

        refactor = AgentTask(
            f"refactor:{attempt}:{failed.task.task_id}",
            AgentRole.REFACTORER,
            f"Refactor the validated fix from {debug.task_id} without changing required behavior.",
            failed.task.resources,
            depends_on=(debug.task_id,),
        )
        refactor_result = self._execute(refactor)
        completed.append(refactor_result)
        if not refactor_result.result.success:
            return refactor_result

        retest = AgentTask(
            f"test:{attempt}:retest:{failed.task.task_id}",
            AgentRole.TESTER,
            f"Mandatory retest after {refactor.task_id}.",
            failed.task.resources,
        )
        retest_result = self._execute(retest)
        completed.append(retest_result)
        return retest_result

    def run(self, tasks: Sequence[AgentTask]) -> RuntimeReport:
        required = (AgentRole.IMPLEMENTER, AgentRole.TESTER, AgentRole.REVIEWER, AgentRole.INTEGRATOR)
        templates = {task.role: task for task in tasks}
        missing = [role.value for role in required if role not in templates]
        if missing:
            return RuntimeReport((), error=f"required development role missing: {', '.join(missing)}")

        completed: list[RuntimeTaskResult] = []
        rounds = 1
        test_attempts = 0
        review_attempts = 0

        manager = templates.get(AgentRole.MANAGER)
        if manager is not None:
            result = self._execute(manager)
            completed.append(result)
            if not result.result.success:
                return RuntimeReport(tuple(completed), manager.task_id, result.result.summary, rounds, 0)

        implementer = self._execute(templates[AgentRole.IMPLEMENTER])
        completed.append(implementer)
        if not implementer.result.success:
            return RuntimeReport(tuple(completed), implementer.task.task_id, implementer.result.summary, rounds, 0)

        tester = self._execute(templates[AgentRole.TESTER])
        completed.append(tester)
        while not tester.result.success:
            if test_attempts >= self._max_rounds - 1:
                return RuntimeReport(tuple(completed), tester.task.task_id, tester.result.summary, rounds, test_attempts + review_attempts)
            test_attempts += 1
            rounds = max(rounds, test_attempts + 1)
            repaired = self._quality_repair(tester, test_attempts, completed)
            if repaired is None:
                return RuntimeReport(
                    tuple(completed),
                    tester.task.task_id,
                    "TEST failed; Debugger and Refactorer are required",
                    rounds,
                    test_attempts + review_attempts,
                )
            if repaired.task.role in (AgentRole.DEBUGGER, AgentRole.REFACTORER):
                return RuntimeReport(
                    tuple(completed),
                    repaired.task.task_id,
                    repaired.result.summary,
                    rounds,
                    test_attempts + review_attempts,
                )
            tester = repaired

        reviewer = self._execute(templates[AgentRole.REVIEWER])
        completed.append(reviewer)
        while not reviewer.result.success:
            if review_attempts >= self._max_rounds - 1:
                return RuntimeReport(
                    tuple(completed),
                    reviewer.task.task_id,
                    reviewer.result.summary,
                    rounds,
                    test_attempts + review_attempts,
                )
            review_attempts += 1
            rounds = max(rounds, review_attempts + 1)
            repaired = self._quality_repair(reviewer, review_attempts, completed)
            if repaired is None:
                return RuntimeReport(
                    tuple(completed),
                    reviewer.task.task_id,
                    "Review failed; Debugger and Refactorer are required",
                    rounds,
                    test_attempts + review_attempts,
                )
            if repaired.task.role in (AgentRole.DEBUGGER, AgentRole.REFACTORER):
                return RuntimeReport(
                    tuple(completed),
                    repaired.task.task_id,
                    repaired.result.summary,
                    rounds,
                    test_attempts + review_attempts,
                )
            if not repaired.result.success:
                reviewer = repaired
                continue
            rereview = self._execute(
                AgentTask(
                    f"review:{review_attempts}:rereview",
                    AgentRole.REVIEWER,
                    f"Re-review after {repaired.task.task_id}.",
                    reviewer.task.resources,
                )
            )
            completed.append(rereview)
            reviewer = rereview

        integrator = self._execute(templates[AgentRole.INTEGRATOR])
        completed.append(integrator)
        if not integrator.result.success:
            return RuntimeReport(
                tuple(completed),
                integrator.task.task_id,
                integrator.result.summary,
                rounds,
                test_attempts + review_attempts,
            )
        return RuntimeReport(
            tuple(completed),
            rounds=rounds,
            repair_attempts=test_attempts + review_attempts,
            integration_ready=True,
        )
