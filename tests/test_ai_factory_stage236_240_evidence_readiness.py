import math

from core.ai_factory_stage236_240_evidence_readiness import (
    stage236_independent_source_corroboration,
    stage237_evaluator_drift,
    stage238_validate_preregistration,
    stage239_build_retention_manifest,
    stage240_readiness_summary,
)


D1 = "a" * 64
D2 = "b" * 64


def test_236_requires_distinct_sources_and_matching_digests():
    rows = [
        {"evidence_id": "e1", "source_id": "source-a", "digest": D1},
        {"evidence_id": "e1", "source_id": "source-b", "digest": D1},
    ]
    assert stage236_independent_source_corroboration(observations=rows)["status"] == "SOURCES_CORROBORATED"
    conflict = [*rows[:1], {**rows[1], "digest": D2}]
    result = stage236_independent_source_corroboration(observations=conflict)
    assert result["status"] == "CORROBORATION_FAILED"
    assert result["conflicting_evidence_ids"] == ["e1"]
    assert stage236_independent_source_corroboration(observations=[rows[0]])["status"] == "CORROBORATION_FAILED"
    assert stage236_independent_source_corroboration(observations=rows, held=True)["status"] == "INSUFFICIENT_EVIDENCE"


def test_236_rejects_duplicate_source_and_malformed_digest():
    row = {"evidence_id": "e", "source_id": "s", "digest": D1}
    assert stage236_independent_source_corroboration(observations=[row, row])["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage236_independent_source_corroboration(observations=[{**row, "digest": "bad"}])["status"] == "INSUFFICIENT_EVIDENCE"


def test_237_detects_drift_and_rejects_bad_samples_identity_and_nonfinite_values():
    base = {"accuracy": 0.9, "false_positive_rate": 0.1}
    stable = stage237_evaluator_drift(
        baseline_metrics=base, current_metrics={"accuracy": 0.92, "false_positive_rate": 0.11},
        evaluator_id="eval-v1", expected_evaluator_id="eval-v1", sample_count=30,
    )
    assert stable["status"] == "EVALUATOR_STABLE"
    drift = stage237_evaluator_drift(
        baseline_metrics=base, current_metrics={"accuracy": 0.7, "false_positive_rate": 0.2},
        evaluator_id="eval-v1", expected_evaluator_id="eval-v1", sample_count=30,
    )
    assert drift["status"] == "EVALUATOR_DRIFT_DETECTED"
    assert stage237_evaluator_drift(
        baseline_metrics=base, current_metrics=base, evaluator_id="eval-v2",
        expected_evaluator_id="eval-v1", sample_count=30,
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage237_evaluator_drift(
        baseline_metrics=base, current_metrics={"accuracy": math.nan, "false_positive_rate": 0.1},
        evaluator_id="eval-v1", expected_evaluator_id="eval-v1", sample_count=30,
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage237_evaluator_drift(
        baseline_metrics=base, current_metrics=base, evaluator_id="eval-v1",
        expected_evaluator_id="eval-v1", sample_count=2,
    )["status"] == "INSUFFICIENT_EVIDENCE"


def _valid_protocol():
    return {
        "hypothesis": "A bounded change improves the primary metric",
        "primary_metric": "quality_score",
        "dataset_digest": D1,
        "suite_digest": D2,
        "analysis_plan": "paired comparison with predefined exclusions",
        "randomization_method": "seeded random assignment",
        "success_threshold": 0.02,
        "sample_size": 12,
        "safety_guardrails": {"safety_score_min": 0.95, "regression_count_max": 0},
        "outcomes_observed": False,
    }


def test_238_requires_complete_frozen_preregistration_before_outcomes():
    valid = stage238_validate_preregistration(
        protocol=_valid_protocol(), registered_at="2026-11-23T10:00:00+09:00"
    )
    assert valid["status"] == "PREREGISTRATION_VALID"
    assert len(valid["protocol_digest"]) == 64
    assert stage238_validate_preregistration(
        protocol={**_valid_protocol(), "outcomes_observed": True},
        registered_at="2026-11-23T10:00:00+09:00",
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage238_validate_preregistration(
        protocol=_valid_protocol(), registered_at="2026-11-23T10:00:00"
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage238_validate_preregistration(
        protocol={**_valid_protocol(), "sample_size": True},
        registered_at="2026-11-23T10:00:00+09:00",
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_239_builds_stable_retention_manifest_and_rejects_expired_or_duplicate_artifacts():
    artifacts = [{
        "artifact_id": "run-1", "digest": D1, "provenance_ref": "actions://run/1",
        "created_at": "2026-11-22T10:00:00Z", "retain_until": "2027-11-22T10:00:00Z",
    }]
    result = stage239_build_retention_manifest(
        artifacts=artifacts, evaluated_at="2026-11-23T10:00:00Z"
    )
    assert result["status"] == "RETENTION_MANIFEST_VALID"
    assert len(result["manifest_digest"]) == 64
    assert stage239_build_retention_manifest(
        artifacts=[*artifacts, *artifacts], evaluated_at="2026-11-23T10:00:00Z"
    )["status"] == "INSUFFICIENT_EVIDENCE"
    expired = [{**artifacts[0], "retain_until": "2026-11-22T11:00:00Z"}]
    assert stage239_build_retention_manifest(
        artifacts=expired, evaluated_at="2026-11-23T10:00:00Z"
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_240_requires_all_gates_and_never_grants_authority():
    good = {
        "corroboration": {"status": "SOURCES_CORROBORATED"},
        "evaluator": {"status": "EVALUATOR_STABLE"},
        "preregistration": {"status": "PREREGISTRATION_VALID"},
        "retention": {"status": "RETENTION_MANIFEST_VALID"},
    }
    ready = stage240_readiness_summary(**good)
    assert ready["status"] == "EVIDENCE_READY_FOR_SEPARATE_REVIEW"
    assert ready["task_execution_authorized"] is False
    assert ready["experiment_execution_authorized"] is False
    assert ready["model_change_authorized"] is False
    assert ready["merge_deploy_authorized"] is False
    assert ready["hold_release_authorized"] is False
    blocked = stage240_readiness_summary(**{**good, "evaluator": {"status": "EVALUATOR_DRIFT_DETECTED"}})
    assert blocked["status"] == "READINESS_BLOCKED"
    assert blocked["failed_gates"] == ["evaluator"]
    assert stage240_readiness_summary(**good, held=True)["status"] == "INSUFFICIENT_EVIDENCE"
