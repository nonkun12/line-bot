import pytest

from core.rsi_executor import EvidenceLedger, Observation, RSIControl, RSIExecutor, RSIError
from core.rsi_supervisor import RSIProposalInput, run_bounded_proposal_batch


def make_executor(tmp_path, *, hold=False):
    return RSIExecutor(
        EvidenceLedger(tmp_path / "supervisor.sqlite"),
        control_provider=lambda: RSIControl(hold, False, True, True, 10, False),
        verify_approval=lambda _: False,
        verify_evaluation=lambda _: False,
        executor_id="proposal-supervisor",
    )


def make_input(index=1, outcome="FAIL"):
    return RSIProposalInput(
        (Observation(
            f"supervisor-{index}-a", (str(index % 10) * 64), "model",
            outcome, "bounded test evidence", index,
        ),),
        "a" * 64, "b" * 64, "c" * 64, 1,
    )


def test_supervisor_runs_only_bounded_proposal_ticks(tmp_path):
    executor = make_executor(tmp_path)
    items = iter([make_input(1), make_input(2)])
    batch = run_bounded_proposal_batch(executor, lambda: next(items), max_cycles=2)
    assert batch.completed_count == 2
    assert batch.stopped_reason == "MAX_CYCLES_REACHED"
    assert batch.execution_authorized is False
    assert batch.scheduler_started is False
    assert batch.model_activated is False
    assert all(cycle.status == "PROPOSAL_READY" for cycle in batch.cycles)


def test_supervisor_stops_without_target_and_never_starts_scheduler(tmp_path):
    executor = make_executor(tmp_path)
    batch = run_bounded_proposal_batch(
        executor, lambda: make_input(3, "PASS"), max_cycles=4
    )
    assert batch.completed_count == 1
    assert batch.stopped_reason == "NO_IMPROVEMENT_TARGET"
    assert batch.scheduler_started is False


def test_supervisor_revalidates_global_hold_on_each_tick(tmp_path):
    state = {"hold": False, "calls": 0}

    def control():
        state["calls"] += 1
        return RSIControl(state["hold"], False, True, True, 10, False)

    executor = RSIExecutor(
        EvidenceLedger(tmp_path / "hold.sqlite"), control_provider=control,
        verify_approval=lambda _: False, verify_evaluation=lambda _: False,
        executor_id="proposal-supervisor",
    )

    def source():
        state["hold"] = True
        return make_input(4)

    with pytest.raises(RSIError, match="Global HOLD"):
        run_bounded_proposal_batch(executor, source, max_cycles=1)


def test_supervisor_rejects_unbounded_cycle_count(tmp_path):
    with pytest.raises(RSIError, match="1..4"):
        run_bounded_proposal_batch(make_executor(tmp_path), lambda: make_input(), max_cycles=5)
