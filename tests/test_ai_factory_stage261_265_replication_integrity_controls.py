import hashlib
import json

from core.ai_factory_stage256_260_paired_capability_evaluation import (
    stage256_preregister_evaluation, stage257_validate_paired_results,
    stage258_estimate_paired_gain, stage259_gate_capability_gain,
    stage260_capability_evidence_package,
)
from core.ai_factory_stage261_265_replication_integrity_controls import (
    stage261_validate_stratified_coverage, stage262_validate_environment_parity,
    stage263_validate_contamination_screen, stage264_correct_multiple_comparisons,
    stage265_validate_independent_replication,
)


def _tasks(prefix):
    rows = [
        {"task_id": f"{prefix}-{i:02d}", "task_digest": hashlib.sha256(f"{prefix}-{i}".encode()).hexdigest()}
        for i in range(30)
    ]
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return rows, digest


def _pipeline(prefix):
    tasks, task_set_digest = _tasks(prefix)
    prereg = stage256_preregister_evaluation(
        protocol_id="shared-protocol", metric_name="success",
        metric_direction="higher_is_better", minimum_gain=0.05,
        alpha=0.05, minimum_pairs=30, task_set_digest=task_set_digest,
    )
    observations = [{
        **task, "baseline_score": 0.0, "candidate_score": 1.0,
        "stratum": "general",
    } for task in tasks]
    paired = stage257_validate_paired_results(preregistration=prereg, observations=observations)
    estimate = stage258_estimate_paired_gain(preregistration=prereg, paired_results=paired)
    gate = stage259_gate_capability_gain(preregistration=prereg, estimate=estimate)
    package = stage260_capability_evidence_package(
        preregistration=prereg, paired_results=paired, estimate=estimate, gate=gate)
    return tasks, prereg, observations, paired, estimate, gate, package


def test_261_requires_all_preregistered_strata_quotas():
    _, _, observations, *_ = _pipeline("strata")
    good = stage261_validate_stratified_coverage(
        observations=observations, preregistered_strata={"general": 30})
    assert good["status"] == "STRATIFIED_COVERAGE_VALIDATED"
    bad = stage261_validate_stratified_coverage(
        observations=observations, preregistered_strata={"general": 30, "reasoning": 5})
    assert bad["status"] == "INSUFFICIENT_EVIDENCE"


def test_262_requires_matching_environment_fields():
    manifest = {
        "runtime_digest": "a" * 64, "hardware_class": "cpu-x",
        "precision": "fp32", "sampling_config_digest": "b" * 64,
        "resource_budget_digest": "c" * 64,
    }
    assert stage262_validate_environment_parity(
        baseline_manifest=manifest, candidate_manifest=dict(manifest)
    )["status"] == "ENVIRONMENT_PARITY_DECLARED"
    changed = {**manifest, "precision": "int4"}
    assert stage262_validate_environment_parity(
        baseline_manifest=manifest, candidate_manifest=changed
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_263_requires_per_task_screening_evidence_and_role_separation():
    records = [{
        "task_id": f"t{i}", "screening_evidence_digest": hashlib.sha256(str(i).encode()).hexdigest(),
        "outcome": "no_known_contamination",
    } for i in range(3)]
    assert stage263_validate_contamination_screen(
        task_records=records, evaluator_id="independent-evaluator",
        model_operator_id="model-operator"
    )["status"] == "CONTAMINATION_SCREEN_DECLARED_CLEAR"
    assert stage263_validate_contamination_screen(
        task_records=records, evaluator_id="same", model_operator_id="same"
    )["status"] == "INSUFFICIENT_EVIDENCE"
    contaminated = [{**records[0], "outcome": "possible_overlap"}, *records[1:]]
    assert stage263_validate_contamination_screen(
        task_records=contaminated, evaluator_id="e", model_operator_id="o"
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_264_applies_bonferroni_and_detects_tampered_estimate():
    *_, estimate, _, _ = _pipeline("family")
    result = stage264_correct_multiple_comparisons(estimates=[estimate, estimate], family_alpha=0.05)
    assert result["status"] == "MULTIPLE_COMPARISON_CORRECTION_APPLIED"
    assert result["family_size"] == 2
    assert result["per_comparison_alpha"] == 0.025
    tampered = {**estimate, "mean_gain": 0.2}
    assert stage264_correct_multiple_comparisons(estimates=[tampered])["status"] == "INSUFFICIENT_EVIDENCE"


def test_265_requires_matching_protocol_and_distinct_replication_task_set():
    _, p1, _, _, _, _, package1 = _pipeline("primary")
    _, p2, _, _, _, _, package2 = _pipeline("replication")
    result = stage265_validate_independent_replication(
        primary_preregistration=p1, replication_preregistration=p2,
        primary_package=package1, replication_package=package2,
        primary_evaluator_id="evaluator-a", replication_evaluator_id="evaluator-b",
    )
    assert result["status"] == "INDEPENDENT_REPLICATION_DECLARED"
    assert result["rsi_or_asi_demonstrated"] is False
    assert result["requires_external_audit"] is True
    assert stage265_validate_independent_replication(
        primary_preregistration=p1, replication_preregistration=p1,
        primary_package=package1, replication_package=package1,
        primary_evaluator_id="a", replication_evaluator_id="b",
    )["status"] == "INSUFFICIENT_EVIDENCE"
