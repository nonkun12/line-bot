import hashlib

from core.ai_factory_stage276_280_longitudinal_evaluator_governance import (
    stage276_append_capability_history,
    stage277_measure_evaluator_disagreement,
    stage278_validate_improvement_durability,
    stage279_detect_measurement_bias,
    stage280_evaluate_capability_evidence_governance,
)
from core.ai_factory_stage271_275_evidence_repeatability_regression import (
    stage274_detect_capability_regression,
)
from core.ai_factory_stage266_270_measurement_to_next_experiment import (
    stage269_aggregate_domain_evidence,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def make_guard():
    rows = [{
        "domain": domain, "sample_count": 40, "adjusted_lower_bound": score,
        "minimum_gain": 0.05, "observations_digest": digest(f"obs-{domain}"),
        "protocol_family_digest": digest("protocol"),
    } for domain, score in (("coding", 0.15), ("reasoning", 0.20))]
    return stage274_detect_capability_regression(
        baseline=stage269_aggregate_domain_evidence(domain_results=rows),
        candidate=stage269_aggregate_domain_evidence(domain_results=[{
            **row, "adjusted_lower_bound": row["adjusted_lower_bound"] + 0.02,
            "observations_digest": digest(f"candidate-{row['domain']}"),
        } for row in rows]),
    )


def make_evaluators(spread=0.02):
    return stage277_measure_evaluator_disagreement(evaluations=[
        {"evaluator_id": f"e-{i}", "domain": "coding",
         "score": 0.70 + i * spread / 2, "evidence_digest": digest(f"eval-{i}")}
        for i in range(3)
    ])


def make_durability():
    return stage278_validate_improvement_durability(history=[
        {"recorded_at": f"2026-11-{day:02d}T09:00:00+00:00", "domain": "coding",
         "score": score, "evidence_digest": digest(f"durability-{day}")}
        for day, score in ((1, 0.70), (8, 0.69), (15, 0.68))
    ])


def make_bias():
    return stage279_detect_measurement_bias(subgroup_scores=[
        {"domain": "coding", "group": group, "score": score,
         "evidence_digest": digest(f"group-{group}")}
        for group, score in (("g1", 0.70), ("g2", 0.73), ("g3", 0.71))
    ])


def test_276_creates_linked_history_records_and_rejects_tampering():
    first = make_guard()
    first["recorded_at"] = "2026-11-23T10:00:00+00:00"
    record1 = stage276_append_capability_history(previous=None, observation=first)
    second = make_guard()
    second["recorded_at"] = "2026-11-23T11:00:00+00:00"
    record2 = stage276_append_capability_history(previous=record1, observation=second)
    assert record1["sequence"] == 1 and record2["sequence"] == 2
    assert record2["previous_record_digest"] == record1["record_digest"]
    tampered = {**record1, "sequence": 99}
    assert stage276_append_capability_history(
        previous=tampered, observation=second
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_277_flags_evaluator_disagreement_and_requires_unique_ids():
    assert make_evaluators()["status"] == "EVALUATOR_AGREEMENT_WITHIN_LIMIT"
    rows = [
        {"evaluator_id": f"e-{i}", "domain": "coding", "score": score,
         "evidence_digest": digest(f"spread-{i}")}
        for i, score in enumerate((0.2, 0.5, 0.9))
    ]
    assert stage277_measure_evaluator_disagreement(
        evaluations=rows
    )["status"] == "EVALUATOR_DISAGREEMENT_DETECTED"
    duplicate = [*rows[:2], {**rows[2], "evaluator_id": "e-0"}]
    assert stage277_measure_evaluator_disagreement(
        evaluations=duplicate
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_278_detects_decay_and_requires_ordered_observations():
    assert make_durability()["status"] == "IMPROVEMENT_DURABILITY_PASSED"
    rows = [
        {"recorded_at": f"2026-11-{day:02d}T09:00:00+00:00", "domain": "coding",
         "score": score, "evidence_digest": digest(f"decay-{day}")}
        for day, score in ((1, 0.8), (8, 0.6), (15, 0.7))
    ]
    assert stage278_validate_improvement_durability(
        history=rows
    )["status"] == "IMPROVEMENT_DURABILITY_FAILED"
    assert stage278_validate_improvement_durability(
        history=list(reversed(rows))
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_279_flags_declared_subgroup_gaps():
    assert make_bias()["status"] == "DECLARED_GROUP_GAPS_WITHIN_LIMIT"
    rows = [
        {"domain": "coding", "group": group, "score": score,
         "evidence_digest": digest(f"gap-{group}")}
        for group, score in (("g1", 0.2), ("g2", 0.8))
    ]
    assert stage279_detect_measurement_bias(
        subgroup_scores=rows
    )["status"] == "MEASUREMENT_BIAS_FLAGGED"


def test_280_unified_gate_requires_all_sealed_components():
    guard = make_guard()
    guard["recorded_at"] = "2026-11-23T10:00:00+00:00"
    history = stage276_append_capability_history(previous=None, observation=guard)
    evaluator, durability, bias = make_evaluators(), make_durability(), make_bias()
    result = stage280_evaluate_capability_evidence_governance(
        history_record=history, evaluator_result=evaluator,
        durability_result=durability, bias_result=bias
    )
    assert result["status"] == "CAPABILITY_EVIDENCE_GOVERNANCE_PASSED"
    assert result["capability_gain_proven"] is False
    assert result["experiment_execution_authorized"] is False
    assert stage280_evaluate_capability_evidence_governance(
        history_record=history, evaluator_result=evaluator,
        durability_result=durability,
        bias_result={**bias, "status": "MEASUREMENT_BIAS_FLAGGED"}
    )["status"] == "INSUFFICIENT_EVIDENCE"
