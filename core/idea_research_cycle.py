"""End-to-end coordinator for the safe Idea AI research cycle.

The coordinator connects planning, validated hypotheses, persisted evidence,
and evidence-informed ideation. It does not invoke agents or run experiments.
"""
from __future__ import annotations

from core.idea_ai import Idea, IdeaAgent
from core.idea_evidence import ExperimentEvidence
from core.idea_evidence_store import ExperimentEvidenceStore
from core.idea_hypothesis import ExperimentHypothesis
from core.idea_workflow import build_idea_workflow
from core.multi_agent import TaskBatch

_MAX_CONTEXT_ITEMS = 8


class IdeaResearchCycle:
    """Explicit coordinator; every state-changing call is made by its caller."""

    def __init__(
        self,
        evidence_store: ExperimentEvidenceStore,
        *,
        idea_agent: IdeaAgent | None = None,
    ) -> None:
        if not isinstance(evidence_store, ExperimentEvidenceStore):
            raise TypeError("evidence_store must be an ExperimentEvidenceStore")
        self._store = evidence_store
        self._idea_agent = idea_agent or IdeaAgent()

    def plan(
        self,
        focus: str,
        *,
        context: tuple[str, ...] = (),
    ) -> tuple[TaskBatch, ...]:
        """Return ideation → independent critique → synthesis tasks only."""
        return build_idea_workflow(focus, context=context)

    def record_evidence(self, record: ExperimentEvidence) -> None:
        """Persist one caller-supplied measurement record; never executes it."""
        self._store.append(record)

    def propose_next(
        self,
        focus: str,
        hypothesis: ExperimentHypothesis,
        *,
        context: tuple[str, ...] = (),
        limit: int = 5,
    ) -> tuple[Idea, ...]:
        """Load persisted evidence and use only verified threshold outcomes."""
        if not isinstance(hypothesis, ExperimentHypothesis):
            raise TypeError("hypothesis must be an ExperimentHypothesis")
        if not isinstance(context, tuple) or len(context) > _MAX_CONTEXT_ITEMS:
            raise ValueError(f"context must be a tuple with at most {_MAX_CONTEXT_ITEMS} items")
        records = self._store.list_for_hypothesis(hypothesis.hypothesis_id)
        return self._idea_agent.propose_from_evidence(
            focus,
            hypothesis,
            records,
            context=context,
            limit=limit,
        )


__all__ = ["IdeaResearchCycle"]
