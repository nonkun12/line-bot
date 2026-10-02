"""Bounded parallel-loop orchestration primitives.

This module is intentionally not wired into production execution yet.
It provides the safe concurrency boundary for the distributed AI Loop:
- an explicit registry (no autonomous loop creation)
- bounded worker concurrency
- per-resource exclusion to prevent concurrent writes to the same workspace
- a global fail-closed stop event
- explicit loop/task lifecycle state
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable


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
    max_iterations: int = 1

    def __post_init__(self) -> None:
        if not self.loop_id:
            raise ValueError("loop_id is required")
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
    resources: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.task_id or not self.loop_id:
            raise ValueError("task_id and loop_id are required")


Handler = Callable[[LoopTask, LoopState], Awaitable[str]]


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
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.registry = registry
        self._concurrency = asyncio.Semaphore(max_concurrency)
        self._resource_locks: dict[str, asyncio.Lock] = {}
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        """Latch the dispatcher stop; there is deliberately no reset API."""
        self._stop.set()

    def stopped(self) -> bool:
        return self._stop.is_set()

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

    async def run(self, task: LoopTask, handler: Handler) -> LoopState:
        state = self.registry.get(task.loop_id)
        if self._stop.is_set():
            state.status = LoopStatus.STOPPED
            state.last_result = "dispatcher stopped before execution"
            return state
        if state.iterations >= state.spec.max_iterations:
            state.status = LoopStatus.FAILED
            state.last_result = "max iterations exceeded"
            return state

        state.status = LoopStatus.RUNNING
        async with self._concurrency:
            if self._stop.is_set():
                state.status = LoopStatus.STOPPED
                state.last_result = "dispatcher stopped before handler"
                return state
            locks = await self._acquire_resources(task.resources)
            try:
                if self._stop.is_set():
                    state.status = LoopStatus.STOPPED
                    state.last_result = "dispatcher stopped before handler"
                    return state
                state.iterations += 1
                try:
                    state.last_result = await handler(task, state)
                    state.status = LoopStatus.PASSED
                except asyncio.CancelledError:
                    state.status = LoopStatus.STOPPED
                    state.last_result = "task cancelled"
                    raise
                except Exception as exc:
                    state.status = LoopStatus.FAILED
                    state.last_result = f"{type(exc).__name__}: {exc}"
                return state
            finally:
                for lock in reversed(locks):
                    lock.release()


async def run_parallel(
    dispatcher: ParallelLoopDispatcher,
    tasks: tuple[LoopTask, ...],
    handler: Handler,
) -> tuple[LoopState, ...]:
    """Dispatch a fixed task set concurrently; no task creation occurs here."""
    return tuple(await asyncio.gather(*(dispatcher.run(task, handler) for task in tasks)))
