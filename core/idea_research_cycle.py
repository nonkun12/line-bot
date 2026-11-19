"""Composable end-to-end idea research cycle.

The cycle composes proposal planning, hypothesis validation, measurement
classification, evidence attestation, and evidence-based next-idea ranking.
It never invokes agents, runs experiments, writes files, or grants approval.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .idea_ai import Idea, IdeaAgent
from .idea_evidence import (
    EvidenceVerification,
    ExperimentEvidence,
    ExperimentEvidenceLedger,
)
from .idea_hypothesis import ExperimentHypothesis
from .idea_learning import IdeaOutcome
from .idea_workflow import build_idea_workflow
from .multi_agent import TaskBatch

_MAX_IDEAS = 5


@dataclass(frozen=True)
class IdeaResearchCycle:
    focus: str
    context: tuple[str, ...]
    ideas: tuple[Idea, ...]
    workflow: tuple[TaskBatch, ...]
    hypotheses: tuple[ExperimentHypothesis, ...] = ()
    ledger: ExperimentEvidenceLedger = ExperimentEvidenceLedger()

    @classmethod
    def start(
        cls,
        focus: str,
        *,
        context: tuple[str, ...] = (),
        limit: int = _MAX_IDEAS,
    ) -> "IdeaResearchCycle":
        ideas = IdeaAgent().propose(focus, context=context, limit=limit)
        workflow = build_idea_workflow(focus, context=context)
        return cls(
            focus=focus.strip(),
            context=context,
            ideas=ideas,
            workflow=workflow,
        )

    def register_hypothesis(self, hypothesis: ExperimentHypothesis) -> "IdeaResearchCycle":
        if not isinstance(hypothesis, ExperimentHypothesis):
            raise TypeError("hypothesis must be an ExperimentHypothesis")
        if any(item.hypothesis_id == hypothesis.hypothesis_id for item in self.hypotheses):
            raise ValueError("hypothesis_id already exists in this cycle")
        return replace(self, hypotheses=self.hypotheses + (hypothesis,))

    def record_observation(
        self,
        hypothesis_id: str,
        *,
        style: str,
        observed_value: float,
        source_ref: str,
        commit_sha: str,
        environment: str,
        sample_count: int,
        measured_at: str,
        evidence_sha256: str,
        note: str = "",
    ) -> "IdeaResearchCycle":
        hypothesis = next(
            (item for item in self.hypotheses if item.hypothesis_id == hypothesis_id),
            None,
        )
        if hypothesis is None:
            raise ValueError("hypothesis_id is not registered in this cycle")
        if style not in {idea.style for idea in self.ideas}:
            raise ValueError("style must belong to an idea in this cycle")
        record = ExperimentEvidence.from_observation(
            hypothesis,
            style=style,
            observed_value=observed_value,
            source_ref=source_ref,
            commit_sha=commit_sha,
            environment=environment,
            sample_count=sample_count,
            measured_at=measured_at,
            evidence_sha256=evidence_sha256,
            note=note,
        )
        return replace(self, ledger=self.ledger.append(record))

    def attest_evidence(
        self,
        hypothesis_id: str,
        evidence_sha256: str,
        verification: EvidenceVerification,
    ) -> "IdeaResearchCycle":
        if not isinstance(verification, EvidenceVerification):
            raise TypeError("verification must be an EvidenceVerification")
        matches = [
            index for index, record in enumerate(self.ledger.records)
            if record.hypothesis_id == hypothesis_id
            and record.evidence_sha256 == evidence_sha256
        ]
        if len(matches) != 1:
            raise ValueError("exactly one matching evidence record is required")
        index = matches[0]
        record = self.ledger.records[index]
        if record.result == "unverified":
            raise ValueError("ambiguous observation cannot be attested as success or failure")
        if record.verification is not None:
            raise ValueError("evidence is already attested")
        updated = replace(record, verification=verification)
        records = list(self.ledger.records)
        records[index] = updated
        return replace(self, ledger=ExperimentEvidenceLedger(tuple(records)))

    def next_ideas(self, *, limit: int = _MAX_IDEAS) -> tuple[Idea, ...]:
        """Generate the next bounded proposal set from verified evidence only."""
        return IdeaAgent().propose(
            self.focus,
            context=self.context,
            limit=limit,
            outcomes=self.ledger.learning_outcomes(),
        )

    def evidence_snapshot(self) -> str:
        """Return a versioned JSON snapshot for caller-managed persistence."""
        return self.ledger.to_json()


__all__ = ["IdeaResearchCycle"]
