from core.ai_factory_stage436_440_release_readiness import (
    check_blocker_register, check_release_artifact_inventory,
    check_required_validation_results, check_rollback_readiness,
    evaluate_stages_436_440,
)


D = "a" * 64
CHECKS = ["syntax", "review", "tests"]
SHA = "b" * 40


def test_436_requires_unique_artifacts_and_digest_shape():
    good = [{"artifact_id": "bundle", "version": "1", "kind": "source", "sha256": D}]
    assert check_release_artifact_inventory(good)["pass"]
    assert not check_release_artifact_inventory([{**good[0], "sha256": "bad"}])["pass"]


def test_437_requires_each_check_once_successful_on_same_sha():
    results = [{"name": name, "status": "completed", "conclusion": "success", "head_sha": SHA}
               for name in CHECKS]
    assert check_required_validation_results(results, CHECKS)["pass"]
    assert not check_required_validation_results(results[:-1], CHECKS)["pass"]
    assert not check_required_validation_results(
        [*results[:-1], {**results[-1], "head_sha": "c" * 40}], CHECKS
    )["pass"]


def test_438_rejects_unresolved_or_unreferenced_blockers():
    assert check_blocker_register([{"blocker_id": "b1", "status": "resolved",
                                    "resolution_ref": "issue-1"}])["pass"]
    assert not check_blocker_register([{"blocker_id": "b1", "status": "open"}])["pass"]


def test_439_requires_documented_rollback_and_test_declaration():
    good = {"plan_id": "rb1", "owner": "ops", "trigger": "guardrail breach",
            "verification_method": "health check", "evidence_ref": "test-run",
            "steps": ["restore prior version"], "tested": True}
    assert check_rollback_readiness(good)["pass"]
    assert not check_rollback_readiness({**good, "tested": False})["pass"]


def test_440_readiness_does_not_authorize_release():
    args = {
        "artifacts": [{"artifact_id": "bundle", "version": "1", "kind": "source", "sha256": D}],
        "validation_results": [{"name": n, "status": "completed", "conclusion": "success",
                                "head_sha": SHA} for n in CHECKS],
        "required_checks": CHECKS,
        "blockers": [{"blocker_id": "b1", "status": "resolved", "resolution_ref": "ticket"}],
        "rollback_plan": {"plan_id": "rb1", "owner": "ops", "trigger": "guardrail breach",
                          "verification_method": "health check", "evidence_ref": "test-run",
                          "steps": ["restore previous version"], "tested": True},
        "expected_head_sha": SHA,
    }
    result = evaluate_stages_436_440(**args)
    assert result["status"] == "READY_FOR_SEPARATE_REVIEW"
    assert result["release_authorized"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64
    blocked = evaluate_stages_436_440(**{**args, "expected_head_sha": "c" * 40})
    assert blocked["status"] == "BLOCKED"
