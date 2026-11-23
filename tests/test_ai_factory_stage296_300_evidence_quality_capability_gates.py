import hashlib

from core.ai_factory_stage296_300_evidence_quality_capability_gates import (
    stage296_check_evidence_completeness, stage297_check_uncertainty_quality,
    stage298_check_task_family_coverage, stage299_check_cross_run_consistency,
    stage300_integrate_capability_evidence,
)


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


def completeness():
    return stage296_check_evidence_completeness(evidence_records=[
        {"record_id": f"r{i}", "evidence_digest": h(f"r{i}"), "source": "local",
         "method": "paired", "result": "observed"} for i in range(3)
    ], required_fields=["source", "method", "result"])


def uncertainty():
    return stage297_check_uncertainty_quality(domain_intervals=[
        {"domain": "coding", "lower": 0.70, "upper": 0.80, "evidence_digest": h("ci")}
    ])


def coverage():
    return stage298_check_task_family_coverage(task_family_counts=[
        {"family": name, "count": 5, "manifest_digest": h(name)}
        for name in ["coding", "math"]
    ], required_families=["coding", "math"])


def consistency():
    return stage299_check_cross_run_consistency(run_summaries=[
        {"run_id": f"run-{i}", "domain_scores": {"coding": 0.80 + i * 0.01, "math": 0.70},
         "evidence_digest": h(f"run-{i}")} for i in range(3)
    ])


def test_296_requires_complete_unique_records():
    assert completeness()["status"] == "EVIDENCE_COMPLETE"
    result = stage296_check_evidence_completeness(
        evidence_records=[{"record_id": "a", "evidence_digest": h("a"), "source": "x"}],
        required_fields=["source", "result"], minimum_records=1)
    assert result["status"] == "EVIDENCE_INCOMPLETE"
    assert stage296_check_evidence_completeness(
        evidence_records=[{"record_id": "a", "evidence_digest": h("a")}],
        required_fields=["x", "x"])["status"] == "INSUFFICIENT_EVIDENCE"


def test_297_checks_interval_bounds_and_width():
    assert uncertainty()["status"] == "UNCERTAINTY_WITHIN_LIMIT"
    assert stage297_check_uncertainty_quality(domain_intervals=[
        {"domain": "math", "lower": 0.1, "upper": 0.8, "evidence_digest": h("wide")}
    ])["status"] == "UNCERTAINTY_TOO_WIDE"
    assert stage297_check_uncertainty_quality(domain_intervals=[
        {"domain": "math", "lower": 0.9, "upper": 0.1, "evidence_digest": h("bad")}
    ])["status"] == "INSUFFICIENT_EVIDENCE"


def test_298_requires_exact_family_coverage_and_minimum_counts():
    assert coverage()["status"] == "TASK_FAMILY_COVERAGE_PASSED"
    result = stage298_check_task_family_coverage(task_family_counts=[
        {"family": "coding", "count": 4, "manifest_digest": h("c")}
    ], required_families=["coding", "math"])
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    result = stage298_check_task_family_coverage(task_family_counts=[
        {"family": "coding", "count": 2, "manifest_digest": h("c")}
    ], required_families=["coding"], minimum_per_family=3)
    assert result["status"] == "TASK_FAMILY_COVERAGE_GAP"


def test_299_checks_cross_run_domains_and_score_spread():
    assert consistency()["status"] == "CROSS_RUN_CONSISTENT"
    rows = [{"run_id": f"r{i}", "domain_scores": {"coding": score},
             "evidence_digest": h(f"variance-{i}")}
            for i, score in enumerate([0.1, 0.5, 0.9])]
    assert stage299_check_cross_run_consistency(run_summaries=rows)["status"] == "CROSS_RUN_VARIANCE_DETECTED"
    rows[2]["domain_scores"] = {"math": 0.7}
    assert stage299_check_cross_run_consistency(run_summaries=rows)["status"] == "INSUFFICIENT_EVIDENCE"


def test_300_integrates_only_sealed_positive_gates():
    result = stage300_integrate_capability_evidence(
        completeness_result=completeness(), uncertainty_result=uncertainty(),
        coverage_result=coverage(), consistency_result=consistency())
    assert result["status"] == "CAPABILITY_EVIDENCE_QUALITY_PASSED"
    assert result["asi_demonstrated"] is False
    tampered = {**coverage(), "family_counts": {}}
    assert stage300_integrate_capability_evidence(
        completeness_result=completeness(), uncertainty_result=uncertainty(),
        coverage_result=tampered, consistency_result=consistency()
    )["status"] == "INSUFFICIENT_EVIDENCE"
