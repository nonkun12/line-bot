"""Evidence provenance and verified-outcome adapter for Idea AI.

This module classifies recorded measurements against a declared hypothesis.
It does not run experiments, verify external artifacts, persist records, or grant
approval. A record marked verified must have been independently checked upstream.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

from core.idea_hypothesis import ExperimentHypothesis
from core.idea_learning import IdeaOutcome

_MAX_ID_CHARS = 120
_MAX_REFS = 8
_MAX_REF_CHARS = 300
_MAX_RECORDS = 500
_MAX_PROVENANCE_CHARS = 300


def _text(value: str, field: str, limit: int = _MAX_ID_CHARS) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    if len(value) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")


@dataclass(frozen=True)
class ExperimentEvidence:
    """A measurement record with provenance and an explicit review state."""

    experiment_id: str
    hypothesis_id: str
    style: str
    measured_value: float
    evidence_refs: tuple[str, ...]
    code_revision: str
    environment: str
    verification_status: str = "pending"
    verified_by: str = ""

    def __post_init__(self) -> None:
        _text(self.experiment_id, "experiment_id")
        _text(self.hypothesis_id, "hypothesis_id")
        _text(self.style, "style", 64)
        _text(self.code_revision, "code_revision", 100)
        _text(self.environment, "environment", 500)
        if isinstance(self.measured_value, bool) or not isinstance(self.measured_value, (int, float)) or not isfinite(self.measured_value):
            raise ValueError("measured_value must be a finite number")
        if not isinstance(self.verification_status, str) or self.verification_status not in {"pending", "verified", "rejected"}:
            raise ValueError("verification_status must be pending, verified, or rejected")
        if self.verification_status == "verified":
            _text(self.verified_by, "verified_by")
        elif self.verified_by:
            raise ValueError("verified_by is only valid for verified records")
        if not isinstance(self.evidence_refs, tuple) or not 1 <= len(self.evidence_refs) <= _MAX_REFS:
            raise ValueError(f"evidence_refs must contain 1 to {_MAX_REFS} references")
        for ref in self.evidence_refs:
            _text(ref, "evidence reference", _MAX_REF_CHARS)


def classify_measurement(
    hypothesis: ExperimentHypothesis,
    measured_value: float,
) -> str:
    """Return success/failure only outside the predeclared threshold gray zone."""
    if not isinstance(hypothesis, ExperimentHypothesis):
        raise TypeError("hypothesis must be an ExperimentHypothesis")
    if isinstance(measured_value, bool) or not isinstance(measured_value, (int, float)) or not isfinite(measured_value):
        raise ValueError("measured_value must be a finite number")
    if hypothesis.direction == "increase":
        if measured_value >= hypothesis.success_threshold:
            return "success"
        if measured_value <= hypothesis.failure_threshold:
            return "failure"
    else:
        if measured_value <= hypothesis.success_threshold:
            return "success"
        if measured_value >= hypothesis.failure_threshold:
            return "failure"
    return "unverified"


def build_verified_idea_outcomes(
    hypothesis: ExperimentHypothesis,
    records: Iterable[ExperimentEvidence],
) -> tuple[IdeaOutcome, ...]:
    """Convert independently verified records into bounded learning signals.

    Pending/rejected records and measurements in the threshold gray zone are
    retained as unverified signals, which rank_idea_styles deliberately ignores.
    """
    if not isinstance(hypothesis, ExperimentHypothesis):
        raise TypeError("hypothesis must be an ExperimentHypothesis")
    bounded = tuple(records)
    if len(bounded) > _MAX_RECORDS:
        bounded = bounded[-_MAX_RECORDS:]
    seen: set[str] = set()
    outcomes: list[IdeaOutcome] = []
    for record in bounded:
        if not isinstance(record, ExperimentEvidence):
            raise TypeError("records must contain ExperimentEvidence values")
        if record.experiment_id in seen:
            raise ValueError(f"duplicate experiment_id: {record.experiment_id}")
        seen.add(record.experiment_id)
        if record.hypothesis_id != hypothesis.hypothesis_id:
            raise ValueError("record hypothesis_id does not match hypothesis")
        measured_result = classify_measurement(hypothesis, record.measured_value)
        result = (
            measured_result
            if record.verification_status == "verified"
            else "unverified"
        )
        provenance = (
            f"{record.experiment_id}; reviewer={record.verified_by or 'pending'}; "
            f"rev={record.code_revision}; env={record.environment}; "
            f"refs={','.join(record.evidence_refs)}"
        )
        if len(provenance) > _MAX_PROVENANCE_CHARS:
            raise ValueError("combined evidence provenance exceeds 300 characters")
        outcomes.append(IdeaOutcome(record.style, result, provenance))
    return tuple(outcomes)


__all__ = [
    "ExperimentEvidence",
    "build_verified_idea_outcomes",
    "classify_measurement",
]
