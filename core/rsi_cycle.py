"""End-to-end bounded RSI proposal cycle.

This orchestrator closes the observe -> diagnose -> hypothesize -> optional local
advice -> plan -> select loop. It intentionally stops before experiment execution:
the separate approval, local runner, and independent-evaluation boundaries remain
mandatory and are never inferred from model output.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .rsi_executor import (
    Diagnosis,
    ExperimentPlan,
    Hypothesis,
    Observation,
    RSIError,
    RSIExecutor,
)


class Advisor(Protocol):
    def advise(self, diagnosis: Diagnosis, hypothesis: Hypothesis): ...


@dataclass(frozen=True)
class RSIProposalCycle:
    observations_count: int
    diagnoses: tuple[Diagnosis, ...]
    hypotheses: tuple[Hypothesis, ...]
    advisor_notes: tuple[object, ...]
    plans: tuple[ExperimentPlan, ...]
    selected_plan: ExperimentPlan | None
    status: str
    execution_authorized: bool = False
    human_approval_granted: bool = False
    evaluation_certified: bool = False
    model_activated: bool = False


def run_proposal_cycle(
    executor: RSIExecutor,
    observations: tuple[Observation, ...],
    *,
    baseline_digest: str,
    candidate_digest: str,
    protocol_digest: str,
    expected_cost_units: int = 1,
    advisor: Advisor | None = None,
) -> RSIProposalCycle:
    """Run one bounded proposal cycle; never invoke an experiment runner."""
    if not isinstance(executor, RSIExecutor):
        raise RSIError("typed RSIExecutor is required")
    if not isinstance(observations, tuple) or not observations:
        raise RSIError("a non-empty immutable observation tuple is required")

    diagnoses = executor.observe(observations)
    if not diagnoses:
        return RSIProposalCycle(
            len(observations), (), (), (), (), None, "NO_IMPROVEMENT_TARGET"
        )

    hypotheses = executor.hypothesize(diagnoses)
    notes: list[object] = []
    if advisor is not None:
        if not callable(getattr(advisor, "advise", None)):
            raise RSIError("advisor must implement advise(diagnosis, hypothesis)")
        by_diagnosis = {item.diagnosis_id: item for item in diagnoses}
        for hypothesis in hypotheses:
            diagnosis = by_diagnosis.get(hypothesis.diagnosis_id)
            if diagnosis is None:
                raise RSIError("hypothesis diagnosis lineage is missing")
            # Advisor output is inert proposal material. It is not passed to
            # planning, selection, execution, or evaluation as authority.
            notes.append(advisor.advise(diagnosis, hypothesis))

    plans = executor.plan(
        hypotheses,
        baseline_digest=baseline_digest,
        candidate_digest=candidate_digest,
        protocol_digest=protocol_digest,
        expected_cost_units=expected_cost_units,
    )
    selected = executor.select_next(plans) if plans else None
    return RSIProposalCycle(
        len(observations),
        diagnoses,
        hypotheses,
        tuple(notes),
        plans,
        selected,
        "PROPOSAL_READY" if selected is not None else "NO_SAFE_EXPERIMENT",
    )


__all__ = ["RSIProposalCycle", "run_proposal_cycle"]
