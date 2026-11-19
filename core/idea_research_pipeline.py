"""End-to-end planning adapter for the empirical Idea AI cycle.

Combines role-separated research planning, hypothesis-bound evidence review,
and evidence-informed idea selection. It only builds plans and candidates:
it never invokes agents, runs experiments, persists evidence, or executes work.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.idea_ai import Idea, IdeaAgent
from core.idea_evidence import ExperimentEvidence, build_verified_idea_outcomes
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
    """Build a complete non-executing cycle plan from evidence to next ideas.

    Evidence without its originating hypothesis is rejected. Only independently
    verified records can influence ranking; pending/rejected/gray-zone results
    remain unverified and are ignored by the learning ranker.
    """
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


__all__ = ["IdeaResearchPlan", "build_idea_research_plan"]
