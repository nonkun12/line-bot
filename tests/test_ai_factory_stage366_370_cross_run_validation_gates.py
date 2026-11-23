from core.ai_factory_stage366_370_cross_run_validation_gates import (
    check_anomaly_rate,
    check_cohort_coverage,
    check_cross_run_consistency,
    check_independent_validation_declarations,
    evaluate_stages_366_370,
)


def test_stage_366_requires_same_protocol_and_unique_run_ids():
    assert check_cross_run_consistency([
        {"run_id": "r1", "protocol_digest": "p"},
        {"run_id": "r2", "protocol_digest": "p"},
    ])["pass"]
    result = check_cross_run_consistency([
        {"run_id": "r1", "protocol_digest": "p"},
        {"run_id": "r1", "protocol_digest": "q"},
    ])
    assert not result["pass"]
    assert "run_id_duplicate" in result["errors"]
    assert "protocol_digest_mismatch" in result["errors"]


def test_stage__367_rejects_declared_identity_or_lineage_collisions():
    assert check_independent_validation_declarations([
        {"validator_id": "v1", "lineage_id": "l1"},
        {"validator_id": "v2", "lineage_id": "l2"},
    ])["pass"]
    result = check_independent_validation_declarations([
        {"validator_id": "v1", "lineage_id": "l1"},
        {"validator_id": "v2", "lineage_id": "l1"},
    ])
    assert not result["pass"]
    assert result["independence_proven"] is False
    assert "validator_lineage_collision" in result["errors"]


def test_stage__368_fails_closed_for_bad_denominator_and_excess_rate():
    assert check_anomaly_rate(1, 10, 0.1)["pass"]
    assert "anomaly_rate_exceeded" in check_anomaly_rate(2, 10, 0.1)["errors"]
    assert "population_invalid" in check_anomaly_rate(0, 0, 0.1)["errors"]


def test_stage_369_requires_exact_cohort_coverage():
    assert check_cohort_coverage(["a", "b"], ["b", "a"])["pass"]
    result = check_cohort_coverage(["a", "b"], ["a", "c"])
    assert not result["pass"]
    assert result["missing"] == ["b"]
    assert result["unexpected"] == ["c"]


def test_stage_370_integrates_gates_and_never_authorizes_execution():
    args = dict(
        runs=[{"run_id": "r1", "protocol_digest": "p"},
              {"run_id": "r2", "protocol_digest": "p"}],
        validators=[{"validator_id": "v1", "lineage_id": "l1"},
                    {"validator_id": "v2", "lineage_id": "l2"}],
        observed_anomalies=1, population=10, maximum_anomaly_rate=0.1,
        expected_cohorts=["control", "treatment"],
        observed_cohorts=["control", "treatment"],
    )
    passed = evaluate_stages_366_370(**args)
    assert passed["status"] == "PASS"
    assert passed["execution_authorized"] is False
    assert passed["proposal_only"] is True
    assert len(passed["seal"]) == 64

    blocked = evaluate_stages_366_370(**{**args, "observed_anomalies": 2})
    assert blocked["status"] == "BLOCKED"
    assert blocked["execution_authorized"] is False
