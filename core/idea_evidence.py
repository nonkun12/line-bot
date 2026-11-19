"""Provenance-aware, in-memory evidence ledger for idea experiments.

Records are immutable values. Nothing is written to disk or executed.
Only an explicitly reviewed verification record can produce a learning outcome.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from math import isfinite
import re

from .idea_learning import IdeaOutcome
from .idea_hypothesis import ExperimentHypothesis, classify_observation

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
_MAX_RECORDS = 500


def _text(value: str, field: str, limit: int = 500) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be non-empty and <= {limit} characters")


def _timestamp(value: str, field: str) -> None:
    _text(value, field, 64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")


@dataclass(frozen=True)
class EvidenceVerification:
    """A human/reviewer attestation referencing an independently inspectable record."""

    verifier: str
    verification_ref: str
    verified_at: str
    checks: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.verifier, "verifier", 120)
        _text(self.verification_ref, "verification_ref")
        _timestamp(self.verified_at, "verified_at")
        if not isinstance(self.checks, tuple) or not 1 <= len(self.checks) <= 8:
            raise ValueError("checks must contain 1 to 8 items")
        for check in self.checks:
            _text(check, "check", 200)


@dataclass(frozen=True)
class ExperimentEvidence:
    hypothesis_id: str
    style: str
    result: str
    observed_value: float
    metric: str
    source_ref: str
    commit_sha: str
    environment: str
    sample_count: int
    measured_at: str
    evidence_sha256: str
    note: str = ""
    verification: EvidenceVerification | None = None

    def __post_init__(self) -> None:
        _text(self.hypothesis_id, "hypothesis_id", 100)
        _text(self.style, "style", 64)
        if not isinstance(self.result, str) or self.result not in {"success", "failure", "unverified"}:
            raise ValueError("result must be success, failure, or unverified")
        if isinstance(self.observed_value, bool) or not isinstance(self.observed_value, (int, float)):
            raise ValueError("observed_value must be numeric")
        if not isfinite(self.observed_value):
            raise ValueError("observed_value must be finite")
        _text(self.metric, "metric", 200)
        _text(self.source_ref, "source_ref")
        if not isinstance(self.commit_sha, str) or not _COMMIT_RE.fullmatch(self.commit_sha):
            raise ValueError("commit_sha must be a 7 to 40 character lowercase hex SHA")
        _text(self.environment, "environment", 300)
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int) or self.sample_count < 1:
            raise ValueError("sample_count must be a positive integer")
        _timestamp(self.measured_at, "measured_at")
        if not isinstance(self.evidence_sha256, str) or not _SHA256_RE.fullmatch(self.evidence_sha256):
            raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(self.note, str) or len(self.note) > 500:
            raise ValueError("note must be a string <= 500 characters")
        if self.verification is not None and not isinstance(self.verification, EvidenceVerification):
            raise ValueError("verification must be an EvidenceVerification or None")
        if self.result == "unverified" and self.verification is not None:
            raise ValueError("unverified evidence cannot carry a verification attestation")

    @classmethod
    def from_observation(
        cls,
        hypothesis: ExperimentHypothesis,
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
    ) -> "ExperimentEvidence":
        """Create an unverified record with outcome classified from frozen thresholds."""
        if not isinstance(hypothesis, ExperimentHypothesis):
            raise TypeError("hypothesis must be an ExperimentHypothesis")
        result = classify_observation(hypothesis, observed_value)
        return cls(
            hypothesis_id=hypothesis.hypothesis_id,
            style=style,
            result=result,
            observed_value=observed_value,
            metric=hypothesis.metric,
            source_ref=source_ref,
            commit_sha=commit_sha,
            environment=environment,
            sample_count=sample_count,
            measured_at=measured_at,
            evidence_sha256=evidence_sha256,
            note=note,
            verification=None,
        )

    @property
    def is_verified(self) -> bool:
        return self.result in {"success", "failure"} and self.verification is not None

    def to_idea_outcome(self) -> IdeaOutcome:
        """Return an unverified signal unless an attestation is present."""
        result = self.result if self.is_verified else "unverified"
        evidence = (
            f"sha256:{self.evidence_sha256}; source:{self.source_ref}; "
            f"verification:{self.verification.verification_ref}"
            if self.is_verified and self.verification
            else f"unverified evidence sha256:{self.evidence_sha256}"
        )
        return IdeaOutcome(style=self.style, result=result, evidence=evidence[:300])


@dataclass(frozen=True)
class ExperimentEvidenceLedger:
    """Immutable bounded ledger; callers explicitly retain returned instances."""

    records: tuple[ExperimentEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.records, tuple) or len(self.records) > _MAX_RECORDS:
            raise ValueError(f"records must be a tuple of at most {_MAX_RECORDS} items")
        if any(not isinstance(record, ExperimentEvidence) for record in self.records):
            raise TypeError("records must contain ExperimentEvidence values")
        ids = [(record.hypothesis_id, record.source_ref, record.evidence_sha256) for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence record")

    def append(self, record: ExperimentEvidence) -> "ExperimentEvidenceLedger":
        if not isinstance(record, ExperimentEvidence):
            raise TypeError("record must be ExperimentEvidence")
        if any(
            existing.hypothesis_id == record.hypothesis_id
            and existing.source_ref == record.source_ref
            and existing.evidence_sha256 == record.evidence_sha256
            for existing in self.records
        ):
            raise ValueError("duplicate evidence record")
        return ExperimentEvidenceLedger((self.records + (record,))[-_MAX_RECORDS:])

    def learning_outcomes(self) -> tuple[IdeaOutcome, ...]:
        return tuple(record.to_idea_outcome() for record in self.records)


def evidence_digest(content: bytes) -> str:
    """Calculate a digest for caller-supplied evidence bytes; performs no I/O."""
    if not isinstance(content, bytes) or not content:
        raise ValueError("content must be non-empty bytes")
    return sha256(content).hexdigest()


__all__ = [
    "EvidenceVerification",
    "ExperimentEvidence",
    "ExperimentEvidenceLedger",
    "evidence_digest",
]
