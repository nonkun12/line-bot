from core.ai_factory_stage441_445_evidence_integrity import (
    check_evidence_consistency, check_evidence_freshness, check_evidence_identity,
    check_source_independence, evaluate_stages_441_445,
)


def ev(eid="e1", source="s1", observed="2026-11-23T10:00:00Z"):
    return {"evidence_id": eid, "source_id": source, "evidence_type": "test-result",
            "content_sha256": "a" * 64, "observed_at": observed}


def test_441_requires_unique_identity_source_and_digest():
    assert check_evidence_identity([ev()])["pass"]
    assert not check_evidence_identity([ev(), ev()])["pass"]
    assert not check_evidence_identity([{**ev(), "content_sha256": "bad"}])["pass"]


def test_442_rejects_stale_future_and_naive_timestamps():
    rows = [ev(observed="2026-11-23T09:59:00Z")]
    assert check_evidence_freshness(rows, evaluated_at="2026-11-23T10:00:00Z",
                                    max_age_seconds=60)["pass"]
    assert not check_evidence_freshness(rows, evaluated_at="2026-11-23T10:00:00Z",
                                        max_age_seconds=30)["pass"]
    assert not check_evidence_freshness([ev(observed="2026-11-23T10:01:00Z")],
                                        evaluated_at="2026-11-23T10:00:00Z",
                                        max_age_seconds=60)["pass"]
    assert not check_evidence_freshness([ev(observed="2026-11-23T09:59:00")],
                                        evaluated_at="2026-11-23T10:00:00Z",
                                        max_age_seconds=60)["pass"]


def test_443_counts_declared_distinct_sources_only():
    assert check_source_independence([ev(source="a"), ev("e2", "b")], 2)["pass"]
    assert not check_source_independence([ev(), ev("e2")], 2)["pass"]


def test_444_detects_conflicting_values_for_same_claim():
    assert check_evidence_consistency([{"claim_key": "ci", "value": "pass"}])["pass"]
    result = check_evidence_consistency([
        {"claim_key": "ci", "value": "pass"}, {"claim_key": "ci", "value": "fail"}
    ])
    assert not result["pass"]
    assert result["conflicting_claim_keys"] == ["ci"]


def test_445_aggregate_fails_closed_and_never_authorizes():
    result = evaluate_stages_441_445(
        evidence=[ev(), ev("e2", "s2")],
        evaluated_at="2026-11-23T10:01:00Z", max_age_seconds=120,
        required_independent_sources=2, claims=[{"claim_key": "tests", "value": "pass"}],
    )
    assert result["status"] == "PASS"
    assert result["evidence_authoritative"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64
    blocked = evaluate_stages_441_445(
        evidence=[ev()], evaluated_at="2026-11-23T10:01:00Z", max_age_seconds=120,
        required_independent_sources=2, claims=[],
    )
    assert blocked["status"] == "BLOCKED"
