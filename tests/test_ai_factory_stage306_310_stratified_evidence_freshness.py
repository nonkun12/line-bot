import hashlib

from core.ai_factory_stage306_310_stratified_evidence_freshness import (
    stage306_check_stratum_balance,
    stage307_check_scoring_rubric_parity,
    stage308_check_evidence_freshness,
    stage309_check_domain_missingness,
    stage310_integrate_stratified_evidence_quality,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def stratum():
    return stage306_check_stratum_balance(
        baseline_counts={"easy": 10, "hard": 10},
        candidate_counts={"easy": 11, "hard": 9},
    )


def rubric():
    value = digest("rubric-v1")
    return stage307_check_scoring_rubric_parity(
        preregistered_version="v1", observed_version="v1",
        preregistered_digest=value, observed_digest=value,
    )


def freshness():
    return stage308_check_evidence_freshness(
        evidence_created_at="2026-11-23T00:00:00+00:00",
        evaluated_at="2026-11-23T01:00:00+00:00",
        maximum_age_seconds=3600,
    )


def missingness():
    return stage309_check_domain_missingness(
        domain_counts={
            "reasoning": {"observed": 18, "missing": 2},
            "coding": {"observed": 19, "missing": 1},
        },
        maximum_missing_fraction=0.10,
    )


def test_306_stratum_balance_and_minimum_counts():
    assert stratum()["status"] == "STRATUM_BALANCE_PASSED"
    assert stage306_check_stratum_balance(
        baseline_counts={"easy": 10, "hard": 10},
        candidate_counts={"easy": 19, "hard": 1},
        minimum_per_stratum=1,
    )["status"] == "STRATUM_BALANCE_FAILED"
    assert stage306_check_stratum_balance(
        baseline_counts={"easy": 2}, candidate_counts={"easy": 2}
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_307_rubric_exact_parity():
    assert rubric()["status"] == "SCORING_RUBRIC_PARITY_PASSED"
    assert stage307_check_scoring_rubric_parity(
        preregistered_version="v1", observed_version="v2",
        preregistered_digest=digest("rubric-v1"), observed_digest=digest("rubric-v2"),
    )["status"] == "SCORING_RUBRIC_DRIFT"


def test_308_freshness_rejects_stale_future_and_naive():
    assert freshness()["status"] == "EVIDENCE_FRESH"
    assert stage308_check_evidence_freshness(
        evidence_created_at="2026-11-20T00:00:00Z",
        evaluated_at="2026-11-23T00:00:00Z",
    )["status"] == "EVIDENCE_STALE"
    assert stage308_check_evidence_freshness(
        evidence_created_at="2026-11-23T02:00:00",
        evaluated_at="2026-11-23T01:00:00Z",
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_309_domain_missingness_is_checked_per_domain():
    assert missingness()["status"] == "DOMAIN_MISSINGNESS_PASSED"
    assert stage309_check_domain_missingness(
        domain_counts={
            "reasoning": {"observed": 19, "missing": 1},
            "coding": {"observed": 10, "missing": 10},
        },
    )["status"] == "DOMAIN_MISSINGNESS_FAILED"
    assert stage309_check_domain_missingness(
        domain_counts={"coding": {"observed": 1, "missing": 0}},
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_310_integrates_all_sealed_gates_and_fails_closed():
    result = stage310_integrate_stratified_evidence_quality(
        stratum_result=stratum(), rubric_result=rubric(),
        freshness_result=freshness(), missingness_result=missingness(),
    )
    assert result["status"] == "STRATIFIED_EVIDENCE_QUALITY_PASSED"
    assert result["asi_demonstrated"] is False
    tampered = dict(rubric())
    tampered["rubric_version"] = "forged"
    assert stage310_integrate_stratified_evidence_quality(
        stratum_result=stratum(), rubric_result=tampered,
        freshness_result=freshness(), missingness_result=missingness(),
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage310_integrate_stratified_evidence_quality(
        stratum_result=stratum(), rubric_result=rubric(),
        freshness_result=freshness(), missingness_result=missingness(), held=True,
    )["status"] == "INSUFFICIENT_EVIDENCE"
