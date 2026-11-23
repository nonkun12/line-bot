from core.ai_factory_stage406_410_auditability_lineage import (
    check_audit_event_chain, check_evaluator_separation, check_evidence_lineage,
    check_replay_and_duplicate_evidence, evaluate_stages_406_410,
)


def test_stage_406_requires_complete_evidence_lineage():
    good = check_evidence_lineage([{
        "evidence_id": "e1", "source_id": "src1", "producer_id": "p1",
        "created_at": 100, "content_sha256": "a" * 64,
    }])
    assert good["pass"]
    bad = check_evidence_lineage([{"evidence_id": "e1", "created_at": True}])
    assert not bad["pass"]
    assert "source_id_missing:e1" in bad["errors"]
    assert "created_at_invalid:e1" in bad["errors"]


def test_stage_407_rejects_broken_or_noncontiguous_audit_chain():
    assert check_audit_event_chain([
        {"event_id": "a", "sequence": 0, "previous_event_id": None},
        {"event_id": "b", "sequence": 1, "previous_event_id": "a"},
    ])["pass"]
    bad = check_audit_event_chain([
        {"event_id": "a", "sequence": 1, "previous_event_id": "wrong"},
        {"event_id": "a", "sequence": 2, "previous_event_id": "x"},
    ])
    assert not bad["pass"]
    assert any(x.startswith("audit_event_duplicate:") for x in bad["errors"])


def test_stage_408_rejects_replayed_ids_and_fingerprints():
    good = check_replay_and_duplicate_evidence([
        {"evidence_id": "e1", "fingerprint": "f1"},
        {"evidence_id": "e2", "fingerprint": "f2"},
    ])
    assert good["pass"]
    bad = check_replay_and_duplicate_evidence([
        {"evidence_id": "e1", "fingerprint": "same"},
        {"evidence_id": "e2", "fingerprint": "same"},
    ])
    assert not bad["pass"]
    assert "replay_fingerprint_duplicate:same" in bad["errors"]


def test_stage_409_requires_distinct_declared_evaluator_per_scope():
    good = check_evaluator_separation([
        {"scope": "model", "producer_id": "team-a", "evaluator_id": "team-b",
         "separation_attested": True},
    ], required_scopes=["model"])
    assert good["pass"]
    bad = check_evaluator_separation([
        {"scope": "model", "producer_id": "same", "evaluator_id": "same",
         "separation_attested": False},
    ], required_scopes=["model", "data"])
    assert not bad["pass"]
    assert "evaluator_not_independent_by_declaration:model" in bad["errors"]
    assert "evaluator_scope_missing:data" in bad["errors"]


def test_stage_410_aggregates_fail_closed_and_never_grants_authority():
    args = dict(
        lineage_records=[{"evidence_id": "e1", "source_id": "src", "producer_id": "p",
                          "created_at": 100, "content_sha256": "a" * 64}],
        audit_events=[{"event_id": "a", "sequence": 0, "previous_event_id": None}],
        replay_records=[{"evidence_id": "e1", "fingerprint": "f1"}],
        evaluator_assignments=[{"scope": "model", "producer_id": "p",
                                "evaluator_id": "reviewer", "separation_attested": True}],
        required_scopes=["model"],
    )
    passed = evaluate_stages_406_410(**args)
    assert passed["status"] == "PASS"
    assert passed["proposal_only"] is True
    assert passed["execution_authorized"] is False
    assert passed["promotion_authorized"] is False
    assert len(passed["seal"]) == 64
    blocked = evaluate_stages_406_410(**{**args, "audit_events": []})
    assert blocked["status"] == "BLOCKED"
    assert blocked["execution_authorized"] is False
    assert blocked["promotion_authorized"] is False
