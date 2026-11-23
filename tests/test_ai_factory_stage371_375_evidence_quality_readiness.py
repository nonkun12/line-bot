from core.ai_factory_stage371_375_evidence_quality_readiness import (
    check_evidence_category_coverage,
    check_evidence_freshness,
    check_metric_schema_compatibility,
    check_missingness_rate,
    evaluate_stages_371_375,
)


def test_stage_371_rejects_stale_future_and_missing_timestamps():
    assert check_evidence_freshness(
        [{"timestamp": 95}], now_epoch=100, maximum_age_seconds=5
    )["pass"]
    result = check_evidence_freshness(
        [{"timestamp": 80}, {"timestamp": 101}, {}],
        now_epoch=100, maximum_age_seconds=5,
    )
    assert not result["pass"]
    assert "evidence_stale:0" in result["errors"]
    assert "timestamp_in_future:1" in result["errors"]
    assert "timestamp_invalid:2" in result["errors"]


def test_stage_372_requires_compatible_declared_metric_schemas():
    assert check_metric_schema_compatibility([
        {"schema_digest": "abc"}, {"schema_digest": "abc"}
    ])["pass"]
    assert "schema_digest_mismatch" in check_metric_schema_compatibility([
        {"schema_digest": "abc"}, {"schema_digest": "def"}
    ])["errors"]


def test_stage_373_bounds_missingness_and_rejects_bad_counts():
    assert check_missingness_rate(10, 2, 0.2)["pass"]
    assert "missingness_rate_exceeded" in check_missingness_rate(10, 3, 0.2)["errors"]
    assert "total_fields_invalid" in check_missingness_rate(0, 0, 0.2)["errors"]
    assert "missing_exceeds_total" in check_missingness_rate(2, 3, 1.0)["errors"]


def test_stage_374_requires_exact_evidence_category_coverage():
    assert check_evidence_category_coverage(["metrics", "logs"], ["logs", "metrics"])["pass"]
    result = check_evidence_category_coverage(["metrics", "logs"], ["metrics", "trace"])
    assert result["missing"] == ["logs"]
    assert result["unexpected"] == ["trace"]
    assert not result["pass"]


def test_stage_375_aggregates_checks_and_never_authorizes_execution():
    args = dict(
        evidence=[{"timestamp": 99}], now_epoch=100, maximum_age_seconds=10,
        metric_schemas=[{"schema_digest": "s1"}, {"schema_digest": "s1"}],
        total_fields=10, missing_fields=1, maximum_missing_rate=0.1,
        required_categories=["metrics", "logs"],
        supplied_categories=["metrics", "logs"],
    )
    passed = evaluate_stages_371_375(**args)
    assert passed["status"] == "PASS"
    assert passed["execution_authorized"] is False
    assert passed["proposal_only"] is True
    assert len(passed["seal"]) == 64

    blocked = evaluate_stages_371_375(**{**args, "missing_fields": 2})
    assert blocked["status"] == "BLOCKED"
    assert blocked["execution_authorized"] is False


def test_stage_371_invalid_clock_fails_closed_without_type_error():
    result = check_evidence_freshness(
        [{"timestamp": 10}], now_epoch="10", maximum_age_seconds=-1
    )
    assert not result["pass"]
    assert "now_epoch_invalid" in result["errors"]
    assert "maximum_age_invalid" in result["errors"]
