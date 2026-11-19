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
from .idea_evidence_store import SQLiteIdeaEvidenceStore
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

    def persist_evidence(
        self,
        store: SQLiteIdeaEvidenceStore,
        namespace: str,
        *,
        expected_revision: int,
    ) -> int:
        """Persist this cycle's evidence ledger using caller-managed local storage."""
        if not isinstance(store, SQLiteIdeaEvidenceStore):
            raise TypeError("store must be a SQLiteIdeaEvidenceStore")
        return store.save(
            namespace,
            self.ledger,
            expected_revision=expected_revision,
        )

    def restore_evidence(
        self,
        store: SQLiteIdeaEvidenceStore,
        namespace: str,
    ) -> "IdeaResearchCycle":
        """Restore only the evidence ledger; current ideas and hypotheses are retained."""
        if not isinstance(store, SQLiteIdeaEvidenceStore):
            raise TypeError("store must be a SQLiteIdeaEvidenceStore")
        snapshot = store.load(namespace)
        if snapshot is None:
            raise LookupError("no stored evidence snapshot exists for this namespace")
        return replace(self, ledger=snapshot.ledger)

    def to_json(self) -> str:
        """Serialize the complete resumable cycle as a bounded, versioned snapshot."""
        import json
        from dataclasses import asdict
        from .multi_agent import AgentRole, AgentTask

        def task_data(task):
            return {
                "task_id": task.task_id,
                "role": task.role.value,
                "instruction": task.instruction,
                "resources": sorted(task.resources),
                "depends_on": list(task.depends_on),
                "priority": task.priority,
            }

        payload = {
            "schema_version": 1,
            "focus": self.focus,
            "context": list(self.context),
            "ideas": [{
                "idea_id": idea.idea_id,
                "title": idea.title,
                "rationale": idea.rationale,
                "next_step": idea.next_step,
                "task": task_data(idea.task),
                "style": idea.style,
                "novelty": idea.novelty,
                "positive_impact": idea.positive_impact,
                "safety_boundary": idea.safety_boundary,
            } for idea in self.ideas],
            "hypotheses": [asdict(item) for item in self.hypotheses],
            "ledger": self.ledger.to_json(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded) > 2_000_000:
            raise ValueError("cycle snapshot exceeds 2MB")
        return encoded

    @classmethod
    def from_json(cls, payload: str) -> "IdeaResearchCycle":
        """Restore a validated cycle snapshot; no agent or experiment is executed."""
        import json
        from .idea_ai import Idea
        from .multi_agent import AgentRole, AgentTask
        from .idea_evidence import ExperimentEvidenceLedger

        if not isinstance(payload, str) or len(payload) > 2_000_000:
            raise ValueError("payload must be a string no larger than 2MB")
        try:
            data = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be valid JSON") from exc
        if not isinstance(data, dict) or set(data) != {
            "schema_version", "focus", "context", "ideas", "hypotheses", "ledger"
        }:
            raise ValueError("cycle snapshot has an invalid top-level schema")
        if data["schema_version"] != 1:
            raise ValueError("unsupported cycle snapshot schema version")
        if not isinstance(data["focus"], str) or not data["focus"].strip():
            raise ValueError("focus must be non-empty")
        if not isinstance(data["context"], list) or len(data["context"]) > 8 or any(
            not isinstance(item, str) for item in data["context"]
        ):
            raise ValueError("context must be a list of at most 8 strings")
        if not isinstance(data["ideas"], list) or not 1 <= len(data["ideas"]) <= _MAX_IDEAS:
            raise ValueError("ideas must contain 1 to 5 items")
        if not isinstance(data["hypotheses"], list) or len(data["hypotheses"]) > 100:
            raise ValueError("hypotheses must be a list of at most 100 items")

        ideas = []
        idea_fields = {
            "idea_id", "title", "rationale", "next_step", "task", "style",
            "novelty", "positive_impact", "safety_boundary",
        }
        task_fields = {"task_id", "role", "instruction", "resources", "depends_on", "priority"}
        for item in data["ideas"]:
            if not isinstance(item, dict) or set(item) != idea_fields:
                raise ValueError("idea entry has an invalid schema")
            task = item["task"]
            if not isinstance(task, dict) or set(task) != task_fields:
                raise ValueError("idea task has an invalid schema")
            if not isinstance(task["resources"], list) or not isinstance(task["depends_on"], list):
                raise ValueError("task resources and dependencies must be lists")
            restored_task = AgentTask(
                task_id=task["task_id"],
                role=AgentRole(task["role"]),
                instruction=task["instruction"],
                resources=frozenset(task["resources"]),
                depends_on=tuple(task["depends_on"]),
                priority=task["priority"],
            )
            idea_values = {key: item[key] for key in idea_fields if key != "task"}
            ideas.append(Idea(task=restored_task, **idea_values))

        hypotheses = []
        hypothesis_fields = {
            "hypothesis_id", "statement", "prediction", "metric", "direction",
            "baseline", "success_threshold", "failure_threshold", "baseline_source",
            "measurement_method", "evidence_requirements", "reproducibility_steps",
        }
        seen_ids = set()
        for item in data["hypotheses"]:
            if not isinstance(item, dict) or set(item) != hypothesis_fields:
                raise ValueError("hypothesis entry has an invalid schema")
            values = dict(item)
            for key in ("evidence_requirements", "reproducibility_steps"):
                if not isinstance(values[key], list):
                    raise ValueError(f"{key} must be a list")
                values[key] = tuple(values[key])
            hypothesis = ExperimentHypothesis(**values)
            if hypothesis.hypothesis_id in seen_ids:
                raise ValueError("duplicate hypothesis_id in cycle snapshot")
            seen_ids.add(hypothesis.hypothesis_id)
            hypotheses.append(hypothesis)

        ledger = ExperimentEvidenceLedger.from_json(data["ledger"])
        if any(record.hypothesis_id not in seen_ids for record in ledger.records):
            raise ValueError("ledger contains evidence for an unregistered hypothesis")
        if any(record.style not in {idea.style for idea in ideas} for record in ledger.records):
            raise ValueError("ledger contains evidence for an unknown idea style")
        return cls(
            focus=data["focus"].strip(),
            context=tuple(data["context"]),
            ideas=tuple(ideas),
            workflow=build_idea_workflow(data["focus"], context=tuple(data["context"])),
            hypotheses=tuple(hypotheses),
            ledger=ledger,
        )

    def evidence_snapshot(self) -> str:
        """Return a versioned JSON snapshot for caller-managed persistence."""
        return self.ledger.to_json()


__all__ = ["IdeaResearchCycle"]
