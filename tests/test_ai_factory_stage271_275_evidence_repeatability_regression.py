import hashlib

from core.ai_factory_stage271_275_evidence_repeatability_regression import (
    _canonical_digest,
    stage271_validate_task_bank_custody_receipt,
    stage272_validate_execution_evidence_receipt,
    stage273_validate_multi_round_replication,
    stage274_detect_capability_regression,
    stage275_generate_research_plan,
)
from core.ai_factory_stage266_270_measurement_to_next_experiment import (
    stage269_aggregate_domain_evidence,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def test_271_validates_receipt_structure_without_claiming_authenticity():
    body = {
        "receipt_id": "receipt-1", "custody_authority_id": "archive-a",
        "task_bank_digest": digest("bank"), "received_at": "2026-11-23T08:00:00+00:00",
    }
    receipt = {**body, "receipt_digest": _canonical_digest(body)}
    result = stage271_validate_task_bank_custody_receipt(
        receipt=receipt, expected_manifest_digest=digest("bank")
    )
    assert result["status"] == "TASK_BANK_CUSTODY_RECEIPT_STRUCTURALLY_VALIDATED"
    assert result["external_authentication_verified"] is False
    assert stage271_validate_task_bank_custody_receipt(
        receipt=receipt, expected_manifest_digest=digest("other")
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_272_binds_execution_evidence_and_separates_provenance():
    receipt = {
        "run_id": "run-1", "input_digest": digest("in"), "output_digest": digest("out"),
        "model_config_digest": digest("model"), "task_bank_digest": digest("bank"),
        "runtime_fingerprint_digest": digest("runtime"),
        "observed_fields": ["input_digest", "output_digest"],
        "declared_fields": ["operator_id"],
    }
    result = stage272_validate_execution_evidence_receipt(
        receipt=receipt, expected_task_bank_digest=digest("bank"),
        expected_runtime_digest=digest("runtime")
    )
    assert result["status"] == "EXECUTION_EVIDENCE_RECEIPT_LINKED"
    assert result["external_authentication_verified"] is False
    assert stage272_validate_execution_evidence_receipt(
        receipt=receipt, expected_task_bank_digest=digest("wrong"),
        expected_runtime_digest=digest("runtime")
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_273_requires_three_distinct_positive_rounds():
    rounds = [{
        "round_id": f"round-{i}", "task_set_digest": digest(f"tasks-{i}"),
        "evaluator_id": f"evaluator-{i}", "protocol_digest": digest("protocol"),
        "evidence_digest": digest(f"evidence-{i}"), "positive_gate": True,
    } for i in range(3)]
    result = stage273_validate_multi_round_replication(rounds=rounds)
    assert result["status"] == "MULTI_ROUND_REPLICATION_DECLARED"
    assert result["round_count"] == 3
    assert result["rsi_or_asi_demonstrated"] is False
    duplicate = [*rounds[:2], {**rounds[2], "task_set_digest": rounds[0]["task_set_digest"]}]
    assert stage273_validate_multi_round_replication(
        rounds=duplicate
    )["status"] == "INSUFFICIENT_EVIDENCE"


def make_multidomain(offset=0.0):
    return stage269_aggregate_domain_evidence(domain_results=[{
        "domain": domain, "sample_count": 40,
        "adjusted_lower_bound": lower + offset, "minimum_gain": 0.05,
        "observations_digest": digest(f"observations-{domain}-{offset}"),
        "protocol_family_digest": digest("protocol"),
    } for domain, lower in (("reasoning", 0.18), ("coding", 0.12))])


def test_274_detects_domain_regression_and_requires_same_domains():
    baseline, improved = make_multidomain(), make_multidomain(0.02)
    passed = stage274_detect_capability_regression(baseline=baseline, candidate=improved)
    assert passed["status"] == "CAPABILITY_REGRESSION_GUARD_PASSED"
    regressed = make_multidomain(-0.10)
    failed = stage274_detect_capability_regression(baseline=baseline, candidate=regressed)
    assert failed["status"] == "CAPABILITY_REGRESSION_DETECTED"
    assert failed["regressed_domains"]
    assert stage274_detect_capability_regression(
        baseline=baseline, candidate={"status": "INSUFFICIENT_EVIDENCE"}
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_275_ranks_proposals_only_within_cost_ceiling():
    guard = stage274_detect_capability_regression(
        baseline=make_multidomain(), candidate=make_multidomain(0.02)
    )
    result = stage275_generate_research_plan(
        regression_guard=guard, maximum_cost_units=5,
        candidates=[
            {"candidate_id": "focus-coding", "target_domain": "coding",
             "expected_information_gain": 0.8, "uncertainty": 0.2,
             "estimated_cost_units": 2, "rationale": "Probe the weakest measured domain"},
            {"candidate_id": "expensive", "target_domain": "reasoning",
             "expected_information_gain": 1.0, "uncertainty": 0.1,
             "estimated_cost_units": 9, "rationale": "Out of budget"},
        ],
    )
    assert result["status"] == "NEXT_RESEARCH_PLAN_PROPOSED"
    assert result["proposal_count"] == 1
    assert result["proposals"][0]["candidate_id"] == "focus-coding"
    assert result["plan_is_executable"] is False
    assert result["experiment_execution_authorized"] is False
