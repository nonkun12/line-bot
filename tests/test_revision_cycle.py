import pytest

from agents.media.revision_cycle import plan_next_revision_iteration


def _inputs():
    briefs = {
        "schema_version": "audiovisual-creator-revision-briefs.v1",
        "briefs": [{"brief_id": "BR-1", "preserve": ["story intent"]}],
        "execution_policy": {
            "automatic_revision_application": False,
            "automatic_publication": False,
            "publication_authorized": False,
        },
    }
    candidates = [{
        "candidate_id": "C-1",
        "brief_id": "BR-1",
        "change_summary": "Adjust arrangement",
    }]
    report = {
        "schema_version": "audiovisual-revision-candidate-critic.v1",
        "status": "REVIEW_REQUIRED",
        "findings": [{
            "severity": "warning",
            "code": "required_deliverables_missing",
            "candidate_id": "C-1",
        }],
    }
    return briefs, candidates, report


def test_review_required_creates_bounded_creator_retry():
    briefs, candidates, report = _inputs()

    result = plan_next_revision_iteration(
        briefs, candidates, report, iteration=1, max_iterations=2
    )

    assert result["decision"] == "REQUEST_CREATOR_REVISION"
    assert result["next_iteration"] == 2
    assert result["creator_requests"][0]["candidate_id"] == "C-1"
    assert result["creator_requests"][0]["retry_reason_codes"] == [
        "required_deliverables_missing"
    ]
    assert result["execution_policy"]["model_invocation"] is False
    assert result["execution_policy"]["automatic_asset_changes"] is False
    assert result["execution_policy"]["publication_authorized"] is False


def test_iteration_limit_stops_without_another_creator_request():
    briefs, candidates, report = _inputs()

    result = plan_next_revision_iteration(
        briefs, candidates, report, iteration=2, max_iterations=2
    )

    assert result["decision"] == "ITERATION_LIMIT_REACHED"
    assert result["creator_requests"] == []
    assert result["next_iteration"] is None


def test_hold_stops_cycle():
    briefs, candidates, report = _inputs()
    report["status"] = "HOLD"

    result = plan_next_revision_iteration(
        briefs, candidates, report, iteration=1
    )

    assert result["decision"] == "STOP_HOLD"
    assert result["creator_requests"] == []


def test_structural_pass_waits_for_human_creative_review():
    briefs, candidates, report = _inputs()
    report["status"] = "STRUCTURAL_CHECKS_PASS"

    result = plan_next_revision_iteration(
        briefs, candidates, report, iteration=1
    )

    assert result["decision"] == "AWAIT_HUMAN_CREATIVE_REVIEW"
    assert result["creator_requests"] == []
    assert result["execution_policy"]["human_approval_required_before_application"] is True


def test_unknown_candidate_reference_fails_closed():
    briefs, candidates, report = _inputs()
    report["findings"][0]["candidate_id"] = "UNKNOWN"

    with pytest.raises(ValueError, match="unknown candidate"):
        plan_next_revision_iteration(briefs, candidates, report, iteration=1)


def test_unsafe_brief_policy_is_rejected():
    briefs, candidates, report = _inputs()
    briefs["execution_policy"]["automatic_publication"] = True

    with pytest.raises(ValueError, match="prohibit automatic"):
        plan_next_revision_iteration(briefs, candidates, report, iteration=1)


def test_max_iterations_is_hard_bounded():
    briefs, candidates, report = _inputs()

    with pytest.raises(ValueError, match="between 1 and 3"):
        plan_next_revision_iteration(
            briefs, candidates, report, iteration=1, max_iterations=4
        )
