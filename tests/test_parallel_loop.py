import asyncio

import pytest

from core.parallel_loop import (
    LoopSpec,
    LoopStatus,
    LoopRegistry,
    LoopTask,
    ParallelLoopDispatcher,
    run_parallel,
)


def test_registry_rejects_unregistered_loop():
    registry = LoopRegistry((LoopSpec("hand-sign", frozenset({"TEST"}), frozenset({"uhip"})),))
    dispatcher = ParallelLoopDispatcher(registry)
    with pytest.raises(KeyError):
        asyncio.run(dispatcher.run(LoopTask("t1", "missing"), _handler))


async def _handler(task, state):
    await asyncio.sleep(0)
    return f"PASS:{task.task_id}"


def test_independent_loops_run_in_parallel():
    registry = LoopRegistry((
        LoopSpec("a", frozenset({"DEV"}), frozenset({"a"})),
        LoopSpec("b", frozenset({"DEV"}), frozenset({"b"})),
    ))
    dispatcher = ParallelLoopDispatcher(registry, max_concurrency=2)
    states = asyncio.run(run_parallel(
        dispatcher,
        (LoopTask("t1", "a", frozenset({"a"})), LoopTask("t2", "b", frozenset({"b"}))),
        _handler,
    ))
    assert {state.status for state in states} == {LoopStatus.PASSED}


def test_stop_is_fail_closed_and_not_resettable():
    registry = LoopRegistry((LoopSpec("a", frozenset({"DEV"}), frozenset({"a"})),))
    dispatcher = ParallelLoopDispatcher(registry)
    dispatcher.request_stop()
    state = asyncio.run(dispatcher.run(LoopTask("t1", "a"), _handler))
    assert state.status is LoopStatus.STOPPED
    assert dispatcher.stopped()


def test_same_resource_is_serialized():
    registry = LoopRegistry((
        LoopSpec("a", frozenset({"DEV"}), frozenset({"shared"})),
        LoopSpec("b", frozenset({"DEV"}), frozenset({"shared"})),
    ))
    dispatcher = ParallelLoopDispatcher(registry, max_concurrency=2)
    active = 0
    peak = 0

    async def guarded_handler(task, state):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return "ok"

    asyncio.run(run_parallel(
        dispatcher,
        (LoopTask("t1", "a", frozenset({"shared"})), LoopTask("t2", "b", frozenset({"shared"}))),
        guarded_handler,
    ))
    assert peak == 1
