from core.ai_factory_stage466_470_safe_improvement_governance import (
    check_hold_register, check_recovery_plan, check_review_evidence,
    check_reviewer_separation, evaluate_stages_466_470,
)


def review():
    return {"review_id": "rev-1", "reviewer_id": "reviewer-1", "review_method": "static",
            "reviewed_at": "2026-11-23T10:00:00Z", "head_sha": "abc123",
            "dimensions": ["correctness", "safety"]}


def recovery():
    return {"plan_id": "recovery-1", "trigger_conditions": ["validation-failure"],
            "recovery_steps": ["restore-prior-artifact"], "verification_steps": ["rerun-tests"],
            "owner": "maintainer", "data_preservation": "preserve-evidence",
            "execution_requested": False}


def test_466_requires_exact_head_and_review_dimension_coverage():
    assert check_review_evidence(review(), expected_head="abc123",
                                 required_dimensions=["correctness", "safety"])["pass"]
    assert not check_review_evidence(review(), expected_head="different",
                                     required_dimensions=["correctness"])["pass"]


def test_467_rejects_author_self_review_and_duplicate_reviewer():
    assert check_reviewer_separation([{"reviewer_id": "r1"}, {"reviewer_id": "r2"}],
                                     author_id="author", minimum_reviewers=2)["pass"]
    assert not check_reviewer_separation([{"reviewer_id": "author"}],
                                         author_id="author")["pass"]


def test_468_hold_register_requires_reasons_and_never_accepts_clearance():
    good = [{"hold_id": "h1", "reason": "missing-evidence", "owner": "team",
             "required_evidence": "test-report", "cleared": False}]
    assert check_hold_register(good)["pass"]
    assert not check_hold_register([{**good[0], "cleared": True}])["pass"]


def test_469_validates_recovery_plan_without_execution():
    assert check_recovery_plan(recovery())["pass"]
    assert not check_recovery_plan({**recovery(), "execution_requested": True})["pass"]


def test_470_aggregate_never_releases_hold_or_authorizes_operations():
    result = evaluate_stages_466_470(
        review=review(), expected_head="abc123", required_dimensions=["correctness", "safety"],
        reviewers=[{"reviewer_id": "reviewer-1"}], author_id="author",
        holds=[{"hold_id": "h1", "reason": "tracked", "owner": "team",
                "required_evidence": "proof", "cleared": False}],
        recovery_plan=recovery(),
    )
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["hold_release_authorized"] is False
    assert result["recovery_execution_authorized"] is False
    assert result["merge_authorized"] is False
    assert result["deployment_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64
