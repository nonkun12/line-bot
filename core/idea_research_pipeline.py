"""End-to-end planning adapter for the empirical Idea AI cycle.

Combines role-separated research planning, hypothesis-bound evidence review,
evidence persistence, and evidence-informed idea selection. It only builds
plans and candidates: it never invokes agents or runs experiments.
"""
from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from typing import Iterable

from core.idea_ai import Idea, IdeaAgent
from core.idea_evidence import ExperimentEvidence, build_verified_idea_outcomes
from core.idea_evidence_store import load_evidence_records
from core.idea_hypothesis import ExperimentHypothesis
from core.idea_learning import IdeaOutcome
from core.idea_workflow import build_idea_workflow
from core.multi_agent import TaskBatch

_MAX_EVIDENCE_RECORDS = 500


@dataclass(frozen=True)
class IdeaResearchPlan:
    focus: str
    idea_candidates: tuple[Idea, ...]
    workflow_batches: tuple[TaskBatch, ...]
    learning_outcomes: tuple[IdeaOutcome, ...]
    verified_count: int
    unverified_count: int


def build_idea_research_plan(
    focus: str,
    *,
    context: tuple[str, ...] = (),
    hypothesis: ExperimentHypothesis | None = None,
    evidence_records: Iterable[ExperimentEvidence] = (),
    idea_limit: int = 5,
) -> IdeaResearchPlan:
    """Build a complete non-executing cycle plan from evidence to next ideas."""
    records = tuple(evidence_records)
    if len(records) > _MAX_EVIDENCE_RECORDS:
        raise ValueError(f"evidence_records exceeds {_MAX_EVIDENCE_RECORDS}")
    if records and hypothesis is None:
        raise ValueError("hypothesis is required when evidence_records are supplied")

    outcomes: tuple[IdeaOutcome, ...] = ()
    if hypothesis is not None:
        outcomes = build_verified_idea_outcomes(hypothesis, records)

    ideas = IdeaAgent().propose(
        focus,
        context=context,
        limit=idea_limit,
        outcomes=outcomes,
    )
    workflow = build_idea_workflow(focus, context=context)
    verified_count = sum(item.result in {"success", "failure"} for item in outcomes)
    unverified_count = len(outcomes) - verified_count

    return IdeaResearchPlan(
        focus=focus.strip(),
        idea_candidates=ideas,
        workflow_batches=workflow,
        learning_outcomes=outcomes,
        verified_count=verified_count,
        unverified_count=unverified_count,
    )


def build_idea_research_plan_from_store(
    focus: str,
    *,
    hypothesis: ExperimentHypothesis,
    evidence_store_path: str | PathLike[str],
    context: tuple[str, ...] = (),
    idea_limit: int = 5,
) -> IdeaResearchPlan:
    """Load the explicit evidence store and build the next research plan.

    The store must already exist and pass its permission/provenance checks.
    This function is read-only with respect to the store and never executes work.
    """
    if not isinstance(hypothesis, ExperimentHypothesis):
        raise TypeError("hypothesis must be an ExperimentHypothesis")
    records = load_evidence_records(evidence_store_path)
    return build_idea_research_plan(
        focus,
        context=context,
        hypothesis=hypothesis,
        evidence_records=records,
        idea_limit=idea_limit,
    )


__all__ = [
    "IdeaResearchPlan",
    "build_idea_research_plan",
    "build_idea_research_plan_from_store",
]
