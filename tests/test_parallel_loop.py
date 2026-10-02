import asyncio

import pytest

from core.parallel_loop import (
    LoopSpec,
    LoopStatus,
    LoopRegistry,
    LoopTask,
    ParallelLoopDispatcher,
    TaskExecutionResult,
    run_parallel,
)


def spec(loop_id="a", *, max_iterations=1):
    return LoopSpec(
        loop_id,
        frozenset({"DEV"}),
        frozenset({loop_id, "shared"}),
        frozenset({loop_id, "shared"}),
        max_iterations=max_iterations,
    )


async def _handler(task, state):
    await asyncio.sleep(0)
    return f"PASS:{task.task_id}"


def test_registry_rejects_unregistered_loop():
    registry = LoopRegistry((spec("hand-sign"),))
    dispatcher = ParallelLoopDispatcher(registry)
    with pytest.raises(KeyError):
        asyncio.run(dispatcher.run(
            LoopTask("t1", "missing", frozenset({"hand-sign"}), "DEV", frozenset({"hand-sign"})),
            _handler,
        ))


def test_independent_loops_run_in_parallel():
    registry = LoopRegistry((spec("a"), spec("b")))
    dispatcher = ParallelLoopDispatcher(registry, max_concurrency=2)
    results = asyncio.run(run_parallel(
        dispatcher,
        (
            LoopTask("t1", "a", frozenset({"a"}), "DEV", frozenset({"a"})),
            LoopTask("t2", "b", frozenset({"b"}), "DEV", frozenset({"b"})),
        ),
        _handler,
    ))
    assert {result.status for result in results} == {LoopStatus.PASSED}
    assert {result.task_id for result in results} == {"t1", "t2"}
    assert {result.message for result in results} == {"PASS:t1", "PASS:t2"}


def test_stop_is_fail_closed_and_not_resettable():
    registry = LoopRegistry((spec("a"),))
    dispatcher = ParallelLoopDispatcher(registry)
    dispatcher.request_stop()
    result = asyncio.run(dispatcher.run(
        LoopTask("t1", "a", frozenset({"a"}), "DEV", frozenset({"a"})),
        _handler,
    ))
    assert result.status is LoopStatus.STOPPED
    assert dispatcher.stopped()


def test_same_resource_is_serialized():
    registry = LoopRegistry((spec("a"), spec("b")))
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

    results = asyncio.run(run_parallel(
        dispatcher,
        (
            LoopTask("t1", "a", frozenset({"shared"}), "DEV", frozenset({"shared"})),
            LoopTask("t2", "b", frozenset({"shared"}), "DEV", frozenset({"shared"})),
        ),
        guarded_handler,
    ))
    assert peak == 1
    assert all(result.status is LoopStatus.PASSED for result in results)


def test_agent_and_scope_boundaries_fail_closed():
    registry = LoopRegistry((spec("a"),))
    dispatcher = ParallelLoopDispatcher(registry)
    result = asyncio.run(dispatcher.run(
        LoopTask("t-agent", "a", frozenset({"a"}), "TEST", frozenset({"a"})),
        _handler,
    ))
    assert result.status is LoopStatus.FAILED
    result = asyncio.run(dispatcher.run(
        LoopTask("t-scope", "a", frozenset({"a"}), "DEV", frozenset({"forbidden"})),
        _handler,
    ))
    assert result.status is LoopStatus.FAILED


def test_scope_and_resources_are_required_and_allowlisted():
    with pytest.raises(ValueError):
        LoopTask("t-empty-scope", "a", frozenset({"a"}), "DEV", frozenset())
    with pytest.raises(ValueError):
        LoopTask("t-empty-resources", "a", frozenset(), "DEV", frozenset({"a"}))
    registry = LoopRegistry((spec("a"),))
    dispatcher = ParallelLoopDispatcher(registry)
    result = asyncio.run(dispatcher.run(
        LoopTask("t-bad-resource", "a", frozenset({"forbidden"}), "DEV", frozenset({"a"})),
        _handler,
    ))
    assert result.status is LoopStatus.FAILED


def test_max_iterations_is_atomic():
    registry = LoopRegistry((spec("a", max_iterations=1),))
    dispatcher = ParallelLoopDispatcher(registry, max_concurrency=3)
    results = asyncio.run(run_parallel(
        dispatcher,
        tuple(
            LoopTask(f"t{i}", "a", frozenset({"a"}), "DEV", frozenset({"a"}))
            for i in range(3)
        ),
        _handler,
    ))
    assert sum(result.status is LoopStatus.PASSED for result in results) == 1
    assert sum(result.status is LoopStatus.FAILED for result in results) == 2
    assert registry.get("a").iterations == 1


def test_rejected_task_does_not_overwrite_active_task_status():
    registry = LoopRegistry((spec("a"),))
    dispatcher = ParallelLoopDispatcher(registry, max_concurrency=2)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_handler(task, state):
        started.set()
        await release.wait()
        return "active-pass"

    async def scenario():
        active = asyncio.create_task(dispatcher.run(
            LoopTask("t-active", "a", frozenset({"a"}), "DEV", frozenset({"a"})),
            slow_handler,
        ))
        await started.wait()
        rejected = await dispatcher.run(
            LoopTask("t-rejected", "a", frozenset({"a"}), "DEV", frozenset({"a"})),
            slow_handler,
        )
        assert rejected.status is LoopStatus.FAILED
        assert rejected.task_id == "t-rejected"
        release.set()
        passed = await active
        return rejected, passed

    rejected, passed = asyncio.run(scenario())
    assert passed.status is LoopStatus.PASSED
    assert passed.task_id == "t-active"
    assert registry.get("a").status is LoopStatus.PASSED


def test_stop_after_handler_never_returns_pass():
    registry = LoopRegistry((spec("a"),))
    dispatcher = ParallelLoopDispatcher(registry)

    async def stop_handler(task, state):
        await asyncio.sleep(0)
        dispatcher.request_stop()
        return "handler-pass"

    result = asyncio.run(dispatcher.run(
        LoopTask("t-stop", "a", frozenset({"a"}), "DEV", frozenset({"a"})),
        stop_handler,
    ))
    assert result.status is LoopStatus.STOPPED
    assert registry.get("a").status is LoopStatus.STOPPED


def test_external_stop_provider_fails_closed():
    registry = LoopRegistry((spec("a"),))
    dispatcher = ParallelLoopDispatcher(registry, stop_provider=lambda: True)
    result = asyncio.run(dispatcher.run(
        LoopTask("t-provider-stop", "a", frozenset({"a"}), "DEV", frozenset({"a"})),
        _handler,
    ))
    assert result.status is LoopStatus.STOPPED
