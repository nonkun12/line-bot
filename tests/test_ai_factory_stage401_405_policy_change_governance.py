from core.ai_factory_stage401_405_policy_change_governance import (
    check_change_control_events, check_gate_dependency_graph,
    check_policy_evidence_bindings, check_policy_registry,
    evaluate_stages_401_405,
)


def test_stage_401_requires_unique_versioned_policies_with_sha256():
    good = check_policy_registry([
        {"policy_id": "p1", "version": "v1", "content_sha256": "a" * 64}
    ])
    assert good["pass"]
    bad = check_policy_registry([
        {"policy_id": "p1", "version": "", "content_sha256": "bad"},
        {"policy_id": "p1", "version": "v2", "content_sha256": "b" * 64},
    ])
    assert not bad["pass"]
    assert "policy_id_duplicate:p1" in bad["errors"]
    assert "policy_digest_invalid:p1" in bad["errors"]


def test_stage_402_rejects_missing_and_cyclic_dependencies():
    assert check_gate_dependency_graph([
        {"node_id": "a", "depends_on": []},
        {"node_id": "b", "depends_on": ["a"]},
    ])["pass"]
    result = check_gate_dependency_graph([
        {"node_id": "a", "depends_on": ["b"]},
        {"node_id": "b", "depends_on": ["a"]},
        {"node_id": "c", "depends_on": ["missing"]},
    ])
    assert not result["pass"]
    assert any(x.startswith("dependency_cycle:") for x in result["errors"])
    assert "dependency_missing:c:missing" in result["errors"]


def test_stage_403_requires_exact_policy_evidence_bindings():
    assert check_policy_evidence_bindings(
        [{"policy_id": "p1", "evidence_ids": ["e1"]},
         {"policy_id": "p2", "evidence_ids": ["e2"]}],
        required_policy_ids=["p1", "p2"])["pass"]
    result = check_policy_evidence_bindings(
        [{"policy_id": "p1", "evidence_ids": []}],
        required_policy_ids=["p1", "p2"])
    assert not result["pass"]
    assert "binding_evidence_invalid:p1" in result["errors"]
    assert "policy_binding_missing:p2" in result["errors"]


def test_stage_404_fails_closed_on_revoked_expired_or_future_events():
    assert check_change_control_events([
        {"event_id": "c1", "state": "active", "expires_at": 200, "updated_at": 90}
    ], evaluation_time=100)["pass"]
    result = check_change_control_events([
        {"event_id": "c1", "state": "revoked", "expires_at": 200, "updated_at": 90},
        {"event_id": "c2", "state": "active", "expires_at": 100, "updated_at": 110},
    ], evaluation_time=100)
    assert not result["pass"]
    assert "event_revoked:c1" in result["errors"]
    assert "event_expired:c2" in result["errors"]
    assert "event_updated_in_future:c2" in result["errors"]


def test_stage_405_aggregates_policy_governance_and_never_grants_authority():
    args = dict(
        policies=[{"policy_id": "p1", "version": "v1", "content_sha256": "a" * 64}],
        dependency_nodes=[{"node_id": "g1", "depends_on": []}],
        policy_bindings=[{"policy_id": "p1", "evidence_ids": ["e1"]}],
        required_policy_ids=["p1"],
        change_control_events=[{"event_id": "c1", "state": "active",
                                "expires_at": 200, "updated_at": 90}],
        evaluation_time=100,
    )
    passed = evaluate_stages_401_405(**args)
    assert passed["status"] == "PASS"
    assert passed["proposal_only"] is True
    assert passed["execution_authorized"] is False
    assert passed["promotion_authorized"] is False
    assert len(passed["seal"]) == 64
    blocked = evaluate_stages_401_405(**{**args, "dependency_nodes": [
        {"node_id": "g1", "depends_on": ["missing"]}]})
    assert blocked["status"] == "BLOCKED"
    assert blocked["execution_authorized"] is False
    assert blocked["promotion_authorized"] is False
