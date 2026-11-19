"""Evidence provenance and signed-review adapter for Idea AI.

Measurements are classified against a declared hypothesis. A verified result is
accepted for learning only when its reviewer HMAC matches a caller-supplied
trusted key. This module does not execute experiments or inspect artifacts.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from math import isfinite
from typing import Mapping

from core.idea_hypothesis import ExperimentHypothesis
from core.idea_learning import IdeaOutcome

_MAX_ID_CHARS = 120
_MAX_REFS = 8
_MAX_REF_CHARS = 300
_MAX_RECORDS = 500
_MAX_PROVENANCE_CHARS = 300
_MIN_KEY_BYTES = 32


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
    verification_signature: str = ""

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
        if not isinstance(self.verified_by, str):
            raise ValueError("verified_by must be a string")
        if self.verification_status == "verified":
            _text(self.verified_by, "verified_by")
        elif self.verified_by or self.verification_signature:
            raise ValueError("reviewer identity/signature is only valid for verified records")
        if not isinstance(self.verification_signature, str):
            raise ValueError("verification_signature must be a string")
        if self.verification_signature and (
            len(self.verification_signature) != 64
            or any(char not in "0123456789abcdef" for char in self.verification_signature)
        ):
            raise ValueError("verification_signature must be a lowercase SHA-256 HMAC hex digest")
        if not isinstance(self.evidence_refs, tuple) or not 1 <= len(self.evidence_refs) <= _MAX_REFS:
            raise ValueError(f"evidence_refs must contain 1 to {_MAX_REFS} references")
        for ref in self.evidence_refs:
            _text(ref, "evidence reference", _MAX_REF_CHARS)


def _attestation_payload(record: ExperimentEvidence) -> bytes:
    values = {
        "experiment_id": record.experiment_id,
        "hypothesis_id": record.hypothesis_id,
        "style": record.style,
        "measured_value": record.measured_value,
        "evidence_refs": record.evidence_refs,
        "code_revision": record.code_revision,
        "environment": record.environment,
        "verification_status": record.verification_status,
        "verified_by": record.verified_by,
    }
    return json.dumps(
        values, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sign_evidence_record(record: ExperimentEvidence, reviewer_key: bytes) -> str:
    """Create a reviewer attestation; caller must hold an authorized key."""
    if not isinstance(record, ExperimentEvidence) or record.verification_status != "verified":
        raise ValueError("only verified ExperimentEvidence records can be attested")
    if not isinstance(reviewer_key, bytes) or len(reviewer_key) < _MIN_KEY_BYTES:
        raise ValueError(f"reviewer_key must contain at least {_MIN_KEY_BYTES} bytes")
    return hmac.new(reviewer_key, _attestation_payload(record), hashlib.sha256).hexdigest()


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
    records: tuple[ExperimentEvidence, ...],
    *,
    reviewer_keys: Mapping[str, bytes],
) -> tuple[IdeaOutcome, ...]:
    """Convert signed, independently reviewed records into bounded learning signals.

    Pending/rejected records and threshold gray-zone measurements remain
    unverified. A claimed verified record with an absent/invalid trusted
    signature fails closed instead of entering the learning signal.
    """
    if not isinstance(hypothesis, ExperimentHypothesis):
        raise TypeError("hypothesis must be an ExperimentHypothesis")
    if not isinstance(records, tuple):
        raise TypeError("records must be a bounded tuple")
    if len(records) > _MAX_RECORDS:
        raise ValueError(f"records must contain at most {_MAX_RECORDS} items")
    if not isinstance(reviewer_keys, Mapping):
        raise TypeError("reviewer_keys must be a mapping of reviewer IDs to keys")
    seen: set[str] = set()
    outcomes: list[IdeaOutcome] = []
    for record in records:
        if not isinstance(record, ExperimentEvidence):
            raise TypeError("records must contain ExperimentEvidence values")
        if record.experiment_id in seen:
            raise ValueError(f"duplicate experiment_id: {record.experiment_id}")
        seen.add(record.experiment_id)
        if record.hypothesis_id != hypothesis.hypothesis_id:
            raise ValueError("record hypothesis_id does not match hypothesis")
        measured_result = classify_measurement(hypothesis, record.measured_value)
        if record.verification_status == "verified":
            key = reviewer_keys.get(record.verified_by)
            if not isinstance(key, bytes) or len(key) < _MIN_KEY_BYTES:
                raise ValueError(f"no trusted reviewer key for {record.verified_by}")
            expected = hmac.new(key, _attestation_payload(record), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, record.verification_signature):
                raise ValueError(f"invalid evidence attestation: {record.experiment_id}")
            result = measured_result
        else:
            result = "unverified"
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
    "sign_evidence_record",
]
