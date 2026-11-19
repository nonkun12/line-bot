"""Validated, non-executing contracts for falsifiable idea experiments.

This module records what would be tested and what evidence would count.
It deliberately contains no experiment runner, persistence, or external access.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


_MAX_TEXT_CHARS = 1000
_MAX_LIST_ITEMS = 8
_MAX_LIST_ITEM_CHARS = 300


def _required_text(value: str, field: str, limit: int = _MAX_TEXT_CHARS) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    if len(value) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")


def _bounded_text_list(values: tuple[str, ...], field: str) -> None:
    if not isinstance(values, tuple) or not 1 <= len(values) <= _MAX_LIST_ITEMS:
        raise ValueError(f"{field} must contain 1 to {_MAX_LIST_ITEMS} items")
    for value in values:
        _required_text(value, f"{field} item", _MAX_LIST_ITEM_CHARS)


@dataclass(frozen=True)
class ExperimentHypothesis:
    """A falsifiable experiment specification; never an execution permission."""

    hypothesis_id: str
    statement: str
    prediction: str
    metric: str
    direction: str
    baseline: float
    success_threshold: float
    failure_threshold: float
    baseline_source: str
    measurement_method: str
    evidence_requirements: tuple[str, ...]
    reproducibility_steps: tuple[str, ...]

    def __post_init__(self) -> None:
        _required_text(self.hypothesis_id, "hypothesis_id", 100)
        _required_text(self.statement, "statement")
        _required_text(self.prediction, "prediction")
        _required_text(self.metric, "metric", 200)
        _required_text(self.baseline_source, "baseline_source", 500)
        _required_text(self.measurement_method, "measurement_method", 500)

        if not isinstance(self.direction, str) or self.direction not in {"increase", "decrease"}:
            raise ValueError("direction must be increase or decrease")

        for field_name in ("baseline", "success_threshold", "failure_threshold"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
                raise ValueError(f"{field_name} must be a finite number")

        if self.direction == "increase":
            if not self.failure_threshold < self.baseline < self.success_threshold:
                raise ValueError("increase requires failure_threshold < baseline < success_threshold")
        elif not self.success_threshold < self.baseline < self.failure_threshold:
            raise ValueError("decrease requires success_threshold < baseline < failure_threshold")

        _bounded_text_list(self.evidence_requirements, "evidence_requirements")
        _bounded_text_list(self.reproducibility_steps, "reproducibility_steps")


def classify_observation(hypothesis: ExperimentHypothesis, observed_value: float) -> str:
    """Classify a measurement against predeclared thresholds, without executing it."""
    if not isinstance(hypothesis, ExperimentHypothesis):
        raise TypeError("hypothesis must be an ExperimentHypothesis")
    if isinstance(observed_value, bool) or not isinstance(observed_value, (int, float)):
        raise ValueError("observed_value must be numeric")
    if not isfinite(observed_value):
        raise ValueError("observed_value must be finite")

    if hypothesis.direction == "increase":
        if observed_value >= hypothesis.success_threshold:
            return "success"
        if observed_value <= hypothesis.failure_threshold:
            return "failure"
    else:
        if observed_value <= hypothesis.success_threshold:
            return "success"
        if observed_value >= hypothesis.failure_threshold:
            return "failure"
    return "unverified"


__all__ = ["ExperimentHypothesis", "classify_observation"]
