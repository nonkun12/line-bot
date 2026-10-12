"""Bounded parallel-loop orchestration primitives.

This module is intentionally not wired into production execution yet.
It provides the safe concurrency boundary for the distributed AI Loop:
- an explicit registry (no autonomous loop creation)
- bounded worker concurrency
- per-resource exclusion to prevent concurrent writes to the same workspace
- a global fail-closed stop event
- explicit loop/task lifecycle state
- immutable task-scoped execution results
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable

from core.loop_execution_contract import ExecutionEvidence, ExecutionResult


class LoopStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class LoopSpec:
    loop_id: str
    allowed_agents: frozenset[str]
    allowed_scope: frozenset[str]
    allowed_resources: frozenset[str]
    max_iterations: int = 1

    def __post_init__(self) -> None:
        if not self.loop_id:
            raise ValueError("loop_id is required")
        if not self.allowed_agents:
            raise ValueError("allowed_agents must not be empty")
        if not self.allowed_scope:
            raise ValueError("allowed_scope must not be empty")
        if not self.allowed_resources:
            raise ValueError("allowed_resources must not be empty")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")


@dataclass
class LoopState:
    spec: LoopSpec
    status: LoopStatus = LoopStatus.IDLE
    last_result: str | None = None
    iterations: int = 0


@dataclass(frozen=True)
class LoopTask:
    task_id: str
    loop_id: str
    resources: frozenset[str]
    agent_id: str
    scope: frozenset[str]

    def __post_init__(self) -> None:
        if not self.task_id or not self.loop_id:
            raise ValueError("task_id and loop_id are required")
        if not self.agent_id:
            raise ValueError("agent_id is required")
        if not self.scope:
            raise ValueError("scope must not be empty")
        if not self.resources:
            raise ValueError("resources must not be empty")


@dataclass(frozen=True)
class TaskExecutionResult:
    """Immutable result belonging to exactly one dispatched task."""

    task_id: str
    loop_id: str
    status: LoopStatus
    message: str
    iteration: int | None = None
    evidence: ExecutionEvidence | None = None


Handler = Callable[[LoopTask, LoopState], Awaitable[ExecutionEvidence]]
StopProvider = Callable[[], bool]


class LoopRegistry:
    """Explicit registry; callers must register loops before dispatch."""

    def __init__(self, specs: tuple[LoopSpec, ...]) -> None:
        self._states: dict[str, LoopState] = {}
        for spec in specs:
            if spec.loop_id in self._states:
                raise ValueError(f"duplicate loop_id: {spec.loop_id}")
            self._states[spec.loop_id] = LoopState(spec)

    def get(self, loop_id: str) -> LoopState:
        try:
            return self._states[loop_id]
        except KeyError as exc:
            raise KeyError(f"unregistered loop: {loop_id}") from exc

    def snapshot(self) -> tuple[LoopState, ...]:
        return tuple(self._states.values())


class ParallelLoopDispatcher:
    """Run independent loops concurrently while serializing shared resources."""

    def __init__(
        self,
        registry: LoopRegistry,
        *,
        max_concurrency: int = 2,
        stop_provider: StopProvider,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.registry = registry
        self._concurrency = asyncio.Semaphore(max_concurrency)
        self._resource_locks: dict[str, asyncio.Lock] = {}
        self._iteration_locks: dict[str, asyncio.Lock] = {}
        self._stop = asyncio.Event()
        self._stop_provider = stop_provider

    def request_stop(self) -> None:
        """Latch the dispatcher stop; there is deliberately no reset API."""
        self._stop.set()

    def stopped(self) -> bool:
        return self._is_stopped()

    def _is_stopped(self) -> bool:
        if self._stop.is_set():
            return True
        try:
            return bool(self._stop_provider())
        except Exception:
            # External stop sources fail closed.
            return True

    def validate_task(self, task: LoopTask) -> LoopState:
        """Validate registry membership and declared boundaries without mutating state."""
        state = self.registry.get(task.loop_id)
        if task.agent_id not in state.spec.allowed_agents:
            raise ValueError("agent not allowed for loop")
        if not task.scope.issubset(state.spec.allowed_scope):
            raise ValueError("task scope exceeds loop scope")
        if not task.resources.issubset(state.spec.allowed_resources):
            raise ValueError("task resources exceed loop resources")
        return state

    async def _acquire_resources(self, resources: frozenset[str]) -> list[asyncio.Lock]:
        locks = [self._resource_locks.setdefault(r, asyncio.Lock()) for r in sorted(resources)]
        acquired: list[asyncio.Lock] = []
        try:
            for lock in locks:
                await lock.acquire()
                acquired.append(lock)
            return acquired
        except BaseException:
            for lock in reversed(acquired):
                lock.release()
            raise

    async def run(self, task: LoopTask, handler: Handler) -> TaskExecutionResult:
        try:
            state = self.validate_task(task)
        except ValueError as exc:
            return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.FAILED, str(exc))
        iteration_lock = self._iteration_locks.setdefault(task.loop_id, asyncio.Lock())

        async with iteration_lock:
            if self._is_stopped():
                state.status = LoopStatus.STOPPED
                state.last_result = "dispatcher stopped before admission"
                return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.STOPPED, state.last_result)

            if state.iterations >= state.spec.max_iterations:
                return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.FAILED, "max iterations exceeded")

            # Reservation is atomic with the max-iteration check: no await occurs
            # between admission and iteration consumption.
            state.iterations += 1
            iteration = state.iterations
            state.status = LoopStatus.RUNNING

        async with self._concurrency:
            if self._is_stopped():
                state.status = LoopStatus.STOPPED
                state.last_result = "dispatcher stopped before handler"
                return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.STOPPED, state.last_result, iteration)

            locks = await self._acquire_resources(task.resources)
            try:
                if self._is_stopped():
                    state.status = LoopStatus.STOPPED
                    state.last_result = "dispatcher stopped after resource admission"
                    return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.STOPPED, state.last_result, iteration)

                try:
                    evidence = await handler(task, state)
                    if not isinstance(evidence, ExecutionEvidence):
                        state.status = LoopStatus.FAILED
                        state.last_result = "handler did not return ExecutionEvidence"
                        return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.FAILED, state.last_result, iteration)
                    if evidence.task_id != task.task_id or evidence.loop_id != task.loop_id:
                        state.status = LoopStatus.FAILED
                        state.last_result = "ExecutionEvidence task/loop mismatch"
                        return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.FAILED, state.last_result, iteration, evidence)
                    if self._is_stopped():
                        state.status = LoopStatus.STOPPED
                        state.last_result = "dispatcher stopped after handler"
                        return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.STOPPED, state.last_result, iteration, evidence)
                    if evidence.result is ExecutionResult.PASS:
                        state.last_result = "execution evidence PASS"
                        state.status = LoopStatus.PASSED
                        return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.PASSED, state.last_result, iteration, evidence)
                    if evidence.result is ExecutionResult.STOPPED:
                        state.last_result = evidence.error or "execution evidence stopped"
                        state.status = LoopStatus.STOPPED
                        return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.STOPPED, state.last_result, iteration, evidence)
                    state.last_result = evidence.error or "execution evidence failed"
                    state.status = LoopStatus.FAILED
                    return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.FAILED, state.last_result, iteration, evidence)
                except asyncio.CancelledError:
                    state.status = LoopStatus.STOPPED
                    state.last_result = "task cancelled"
                    raise
                except Exception as exc:
                    state.status = LoopStatus.FAILED
                    state.last_result = f"{type(exc).__name__}: {exc}"
                    return TaskExecutionResult(task.task_id, task.loop_id, LoopStatus.FAILED, state.last_result, iteration)
            finally:
                for lock in reversed(locks):
                    lock.release()


async def run_parallel(
    dispatcher: ParallelLoopDispatcher,
    tasks: tuple[LoopTask, ...],
    handler: Handler,
) -> tuple[TaskExecutionResult, ...]:
    """Validate the entire fixed task set before any handler starts."""
    for task in tasks:
        dispatcher.validate_task(task)
    return tuple(await asyncio.gather(*(dispatcher.run(task, handler) for task in tasks)))
