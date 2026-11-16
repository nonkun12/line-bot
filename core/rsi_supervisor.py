"""Bounded, explicitly invoked RSI proposal supervisor.

This is a synchronous tick/batch adapter, not a scheduler or background worker.
It never executes experiments. Each cycle re-enters the executor's fail-closed
control gate and emits proposal/evidence only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .rsi_cycle import Advisor, RSIProposalCycle, run_proposal_cycle
from .rsi_executor import Observation, RSIError, RSIExecutor, _digest


@dataclass(frozen=True)
class RSIProposalInput:
    observations: tuple[Observation, ...]
    baseline_digest: str
    candidate_digest: str
    protocol_digest: str
    expected_cost_units: int = 1


@dataclass(frozen=True)
class RSISupervisorBatch:
    cycles: tuple[RSIProposalCycle, ...]
    completed_count: int
    stopped_reason: str
    execution_authorized: bool = False
    scheduler_started: bool = False
    model_activated: bool = False


def run_bounded_proposal_batch(
    executor: RSIExecutor,
    input_source: Callable[[], RSIProposalInput],
    *,
    max_cycles: int = 1,
    advisor: Advisor | None = None,
) -> RSISupervisorBatch:
    """Run at most four synchronous proposal ticks; no timer or daemon is started."""
    if not isinstance(executor, RSIExecutor) or not callable(input_source):
        raise RSIError("typed executor and input source are required")
    if type(max_cycles) is not int or not 1 <= max_cycles <= 4:
        raise RSIError("proposal batch bound must be 1..4")
    cycles = []
    stopped_reason = "MAX_CYCLES_REACHED"
    for _ in range(max_cycles):
        source = input_source()
        if not isinstance(source, RSIProposalInput):
            raise RSIError("proposal input source returned an invalid contract")
        if not isinstance(source.observations, tuple) or not source.observations:
            raise RSIError("proposal input observations must be a non-empty tuple")
        for value, label in (
            (source.baseline_digest, "baseline"),
            (source.candidate_digest, "candidate"),
            (source.protocol_digest, "protocol"),
        ):
            _digest(value, label)
        cycle = run_proposal_cycle(
            executor,
            source.observations,
            baseline_digest=source.baseline_digest,
            candidate_digest=source.candidate_digest,
            protocol_digest=source.protocol_digest,
            expected_cost_units=source.expected_cost_units,
            advisor=advisor,
        )
        cycles.append(cycle)
        if cycle.status == "NO_IMPROVEMENT_TARGET":
            stopped_reason = "NO_IMPROVEMENT_TARGET"
            break
    return RSISupervisorBatch(tuple(cycles), len(cycles), stopped_reason)


__all__ = ["RSIProposalInput", "RSISupervisorBatch", "run_bounded_proposal_batch"]
