"""Review-only conversion of ideas into falsifiable experiment plans.

This module structures a proposed test; it never runs experiments, writes
results, grants approval, or changes execution permissions.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

_MAX_FIELD_CHARS = 500
_REQUIRED_FIELDS = (
    "hypothesis",
    "metric",
    "baseline",
    "target",
    "method",
    "falsification_condition",
)
_SPACE = re.compile(r"\s+")


def _required_text(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} is required")
    if len(cleaned) > _MAX_FIELD_CHARS:
        raise ValueError(f"{name} exceeds {_MAX_FIELD_CHARS} characters")
    return cleaned


@dataclass(frozen=True)
class ExperimentPlan:
    """A proposed, human-reviewable experiment with no execution authority."""

    plan_id: str
    source_idea_id: str
    hypothesis: str
    metric: str
    baseline: str
    target: str
    method: str
    falsification_condition: str
    status: str = "DRAFT_REVIEW_REQUIRED"
    human_review_required: bool = True
    execution_approval_granted: bool = False
    execution_performed: bool = False
    result: str = "UNVERIFIED"
    evidence_required: bool = True
    allowed_actions: tuple[str, ...] = ()


def draft_experiment_plan(
    idea: Any,
    *,
    hypothesis: str,
    metric: str,
    baseline: str,
    target: str,
    method: str,
    falsification_condition: str,
) -> ExperimentPlan:
    """Create a deterministic experiment proposal from an existing idea.

    All measurement and falsification details must be supplied explicitly.
    The result remains a draft and cannot be executed by this module.
    """
    idea_id = _required_text("idea.idea_id", getattr(idea, "idea_id", None))
    title = _required_text("idea.title", getattr(idea, "title", None))
    values = {
        name: _required_text(name, value)
        for name, value in {
            "hypothesis": hypothesis,
            "metric": metric,
            "baseline": baseline,
            "target": target,
            "method": method,
            "falsification_condition": falsification_condition,
        }.items()
    }
    if values["baseline"].casefold() == values["target"].casefold():
        raise ValueError("baseline and target must be meaningfully distinct")

    identity = "\0".join(
        [idea_id, title, *(values[name] for name in _REQUIRED_FIELDS)]
    )
    digest = hashlib.sha256(_SPACE.sub(" ", identity).encode("utf-8")).hexdigest()
    return ExperimentPlan(
        plan_id=f"idea-experiment-{digest[:16]}",
        source_idea_id=idea_id,
        **values,
    )


__all__ = ["ExperimentPlan", "draft_experiment_plan"]
