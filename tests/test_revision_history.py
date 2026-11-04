import pytest

from agents.media.revision_history import append_revision_history


def _plan(iteration, status, decision="REQUEST_CREATOR_REVISION"):
    return {
        "schema_version": "audiovisual-revision-cycle-plan.v1",
        "iteration": iteration,
        "decision": decision,
        "critic_status": status,
    }


def _report(status="REVIEW_REQUIRED", findings=None):
    return {
        "schema_version": "audiovisual-revision-candidate-critic.v1",
        "status": status,
        "reviewed_candidate_count": 1,
        "findings": findings if findings is not None else [
            {"code": "candidate_incomplete", "severity": "warning"}
        ],
    }


def test_first_iteration_creates_baseline_without_mutating_input():
    original = {"schema_version": "audiovisual-revision-history.v1", "entries": []}

    result = append_revision_history(
        original, _plan(1, "REVIEW_REQUIRED"), _report()
    )

    assert original["entries"] == []
    assert result["latest_iteration"] == 1
    assert result["entries"][0]["comparison_to_previous"] == "BASELINE"
    assert result["entries"][0]["total_structural_findings"] == 1
    assert result["execution_policy"]["publication_authorized"] is False


def test_second_iteration_records_fewer_structural_findings():
    first = append_revision_history(
        None, _plan(1, "REVIEW_REQUIRED"), _report()
    )
    second_report = _report("STRUCTURAL_CHECKS_PASS", [])
    second = append_revision_history(
        first,
        _plan(2, "STRUCTURAL_CHECKS_PASS", "AWAIT_HUMAN_CREATIVE_REVIEW"),
        second_report,
    )

    assert second["latest_iteration"] == 2
    assert second["entries"][1]["comparison_to_previous"] == "FEWER_STRUCTURAL_FINDINGS"
    assert second["entries"][1]["artistic_quality_assessed"] is False
    assert second["execution_policy"]["automatic_asset_changes"] is False


def test_more_findings_are_reported_as_structural_regression_only():
    first = append_revision_history(
        None, _plan(1, "STRUCTURAL_CHECKS_PASS"), _report("STRUCTURAL_CHECKS_PASS", [])
    )
    second = append_revision_history(
        first, _plan(2, "REVIEW_REQUIRED"), _report()
    )

    assert second["entries"][1]["comparison_to_previous"] == "MORE_STRUCTURAL_FINDINGS"


def test_iteration_must_be_sequential():
    with pytest.raises(ValueError, match="sequential iteration"):
        append_revision_history(
            None, _plan(2, "REVIEW_REQUIRED"), _report()
        )


def test_plan_and_critic_status_must_match():
    with pytest.raises(ValueError, match="statuses do not match"):
        append_revision_history(
            None, _plan(1, "HOLD"), _report("REVIEW_REQUIRED")
        )


def test_invalid_finding_fails_closed():
    with pytest.raises(ValueError, match="string code"):
        append_revision_history(
            None, _plan(1, "REVIEW_REQUIRED"), _report(findings=[{"severity": "warning"}])
        )


def test_existing_history_must_be_sequential():
    broken = {
        "schema_version": "audiovisual-revision-history.v1",
        "entries": [{"iteration": 2, "finding_counts": {}}],
    }
    with pytest.raises(ValueError, match="sequential"):
        append_revision_history(
            broken, _plan(2, "REVIEW_REQUIRED"), _report()
        )
