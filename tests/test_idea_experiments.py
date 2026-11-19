from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.idea_experiments import draft_experiment_plan


@pytest.fixture
def idea():
    return SimpleNamespace(
        idea_id="recombine-1",
        title="recombine: improve agent collaboration",
    )


@pytest.fixture
def fields():
    return {
        "hypothesis": "A shared event contract reduces handoff errors.",
        "metric": "handoff error rate",
        "baseline": "current measured rate over 100 handoffs",
        "target": "at least 20% relative reduction over 100 handoffs",
        "method": "Run the same fixed benchmark against both implementations.",
        "falsification_condition": "Reject if the measured rate does not improve.",
    }


def test_creates_deterministic_review_only_experiment_plan(idea, fields):
    plan = draft_experiment_plan(idea, **fields)
    repeated = draft_experiment_plan(idea, **fields)

    assert plan == repeated
    assert plan.plan_id.startswith("idea-experiment-")
    assert plan.source_idea_id == idea.idea_id
    assert plan.status == "DRAFT_REVIEW_REQUIRED"
    assert plan.human_review_required is True
    assert plan.execution_approval_granted is False
    assert plan.execution_performed is False
    assert plan.result == "UNVERIFIED"
    assert plan.evidence_required is True
    assert plan.allowed_actions == ()


def test_plan_identity_changes_when_hypothesis_or_measurement_changes(idea, fields):
    first = draft_experiment_plan(idea, **fields)
    changed = dict(fields, target="at least 30% relative reduction over 100 handoffs")
    second = draft_experiment_plan(idea, **changed)

    assert first.plan_id != second.plan_id


@pytest.mark.parametrize(
    "field",
    [
        "hypothesis",
        "metric",
        "baseline",
        "target",
        "method",
        "falsification_condition",
    ],
)
def test_requires_every_falsifiable_experiment_field(idea, fields, field):
    invalid = dict(fields, **{field: " "})
    with pytest.raises(ValueError, match="required"):
        draft_experiment_plan(idea, **invalid)


def test_rejects_identical_baseline_and_target(idea, fields):
    invalid = dict(fields, target=fields["baseline"])
    with pytest.raises(ValueError, match="meaningfully distinct"):
        draft_experiment_plan(idea, **invalid)


def test_rejects_unbounded_fields(idea, fields):
    invalid = dict(fields, method="x" * 501)
    with pytest.raises(ValueError, match="exceeds"):
        draft_experiment_plan(idea, **invalid)


def test_requires_an_idea_identity_and_title(fields):
    with pytest.raises(ValueError, match="idea.idea_id"):
        draft_experiment_plan(SimpleNamespace(title="no id"), **fields)
