"""Validated before/after measurements for review-only RSI history."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class SelfImprovementMeasurementRecord:
    """A bounded comparison; it never grants execution authority."""

    proposal_id: str
    metric_name: str
    metric_direction: str
    baseline: float
    candidate: float
    base_sha: str = ""
    produced_sha: str = ""
    test_evidence: tuple[str, ...] = ()
    safety_gate: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, str) or not _ID.fullmatch(self.proposal_id):
            raise ValueError("invalid proposal ID")
        if not isinstance(self.metric_name, str) or not _ID.fullmatch(self.metric_name):
            raise ValueError("invalid metric name")
        if self.metric_direction not in {"maximize", "minimize"}:
            raise ValueError("invalid metric direction")
        for value in (self.baseline, self.candidate):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("measurement values must be finite numbers")
        for value in (self.base_sha, self.produced_sha):
            if value and (not isinstance(value, str) or not _SHA.fullmatch(value)):
                raise ValueError("invalid measurement SHA")
        if len(self.test_evidence) > 10:
            raise ValueError("test evidence exceeds limit")
        if any(not isinstance(item, str) or not _EVIDENCE_ID.fullmatch(item) for item in self.test_evidence):
            raise ValueError("invalid test evidence ID")
        if self.safety_gate not in {"PASS", "FAIL", "UNKNOWN"}:
            raise ValueError("invalid safety gate")

    @property
    def verdict(self) -> str:
        if self.safety_gate == "FAIL":
            return "REGRESSION"
        if self.safety_gate != "PASS" or not self.base_sha or not self.produced_sha or not self.test_evidence:
            return "INSUFFICIENT_EVIDENCE"
        if self.candidate == self.baseline:
            return "NO_CHANGE"
        improved = self.candidate > self.baseline if self.metric_direction == "maximize" else self.candidate < self.baseline
        return "IMPROVED" if improved else "REGRESSION"

    @property
    def measurement_id(self) -> str:
        stable = {
            "proposal_id": self.proposal_id,
            "metric_name": self.metric_name,
            "metric_direction": self.metric_direction,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "base_sha": self.base_sha,
            "produced_sha": self.produced_sha,
            "test_evidence": list(self.test_evidence),
            "safety_gate": self.safety_gate,
        }
        payload = json.dumps(stable, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_record(self) -> dict[str, object]:
        return {
            "record_type": "measurement",
            "measurement_id": self.measurement_id,
            **asdict(self),
            "test_evidence": list(self.test_evidence),
            "verdict": self.verdict,
            "execution_authorized": False,
        }

    @classmethod
    def from_record(cls, row: object) -> "SelfImprovementMeasurementRecord":
        if not isinstance(row, dict) or row.get("record_type") != "measurement":
            raise ValueError("measurement record type is invalid")
        expected = {
            "record_type", "measurement_id", "proposal_id", "metric_name",
            "metric_direction", "baseline", "candidate", "base_sha",
            "produced_sha", "test_evidence", "safety_gate", "verdict",
            "execution_authorized",
        }
        if set(row) != expected or row.get("execution_authorized") is not False:
            raise ValueError("measurement record schema is invalid")
        evidence = row.get("test_evidence")
        if not isinstance(evidence, list):
            raise ValueError("measurement evidence must be a list")
        record = cls(
            proposal_id=row.get("proposal_id"),
            metric_name=row.get("metric_name"),
            metric_direction=row.get("metric_direction"),
            baseline=row.get("baseline"),
            candidate=row.get("candidate"),
            base_sha=row.get("base_sha", ""),
            produced_sha=row.get("produced_sha", ""),
            test_evidence=tuple(evidence),
            safety_gate=row.get("safety_gate"),
        )
        if row.get("measurement_id") != record.measurement_id or row.get("verdict") != record.verdict:
            raise ValueError("measurement identity or verdict mismatch")
        return record


__all__ = ["SelfImprovementMeasurementRecord"]
