from __future__ import annotations

from core.control_tower_decision import ControlTowerDecisionRecord
from scripts.rea_review_candidates import build_review_candidates
from core.rea_control_tower_bridge import rea_result_to_control_tower_decision

SHA = "a" * 40


def report(status="FINDINGS"):
    findings = [] if status == "PASS" else [{
        "finding_id": "0123456789abcdef",
        "category": "python_syntax",
        "severity": "HIGH",
        "target_sha": SHA,
        "evidence": {"path": "core/example.py", "line": 3, "check": "ast_parse_failed"},
    }]
    return {"schema_version": 1, "status": status, "target_sha": SHA,
            "complete": True, "findings_count": len(findings), "findings": findings}


def test_clean_report_maps_to_observe_only_pass_not_task_selection():
    adapter = build_review_candidates(report("PASS"), expected_sha=SHA)
    decision = rea_result_to_control_tower_decision(adapter, expected_sha=SHA)
    assert isinstance(decision, ControlTowerDecisionRecord)
    assert decision.reason_code == "evidence_sufficient"
    assert decision.gate_status == "PASS"
    assert decision.next_action == "OBSERVE_ONLY"
    assert decision.task_template_id is None


def test_findings_are_review_only_not_execution_eligible():
    adapter = build_review_candidates(report(), expected_sha=SHA)
    decision = rea_result_to_control_tower_decision(adapter, expected_sha=SHA)
    assert decision.reason_code == "rea_findings_review_required"
    assert decision.gate_status == "NOT_RUN"
    assert decision.next_action == "OBSERVE_ONLY"
    assert decision.task_template_id is None
    assert not decision.execution_eligible(set(), SHA)


def test_blocked_or_mismatched_result_maps_to_hold():
    adapter = build_review_candidates(report(), expected_sha="b" * 40)
    decision = rea_result_to_control_tower_decision(adapter, expected_sha=SHA)
    assert decision.reason_code == "invalid_state"
    assert decision.gate_status == "BLOCKED"
    assert decision.next_action == "HOLD"
    assert decision.task_template_id is None


def test_tampered_candidate_capabilities_fail_closed():
    adapter = build_review_candidates(report(), expected_sha=SHA)
    adapter["capabilities"]["auto_approval"] = True
    decision = rea_result_to_control_tower_decision(adapter, expected_sha=SHA)
    assert decision.gate_status == "BLOCKED"
    assert decision.next_action == "HOLD"


def test_no_rea_result_can_select_registered_task():
    for status in ("PASS", "FINDINGS"):
        adapter = build_review_candidates(report(status), expected_sha=SHA)
        decision = rea_result_to_control_tower_decision(adapter, expected_sha=SHA)
        assert decision.next_action != "SELECT_REGISTERED_TASK"


def test_bridge_rejects_boolean_candidate_count_and_non_list_candidates():
    adapter = build_review_candidates(report(), expected_sha=SHA)
    bad_count = dict(adapter)
    bad_count["candidate_count"] = True
    bad_candidates = dict(adapter)
    bad_candidates["candidates"] = None

    for invalid in (bad_count, bad_candidates):
        decision = rea_result_to_control_tower_decision(invalid, expected_sha=SHA)
        assert decision.reason_code == "invalid_state"
        assert decision.gate_status == "BLOCKED"
        assert decision.next_action == "HOLD"


def test_bridge_rejects_candidate_with_wrong_review_status_or_execution_action():
    adapter = build_review_candidates(report(), expected_sha=SHA)
    bad_status = {**adapter, "candidates": [dict(adapter["candidates"][0], status="APPROVED")]}
    bad_action = {**adapter, "candidates": [dict(adapter["candidates"][0], next_action="SELECT_REGISTERED_TASK")]}

    for invalid in (bad_status, bad_action):
        decision = rea_result_to_control_tower_decision(invalid, expected_sha=SHA)
        assert decision.gate_status == "BLOCKED"
        assert decision.next_action == "HOLD"
        assert decision.task_template_id is None


def test_bridge_rejects_missing_capability_flags_and_invalid_expected_sha():
    adapter = build_review_candidates(report("PASS"), expected_sha=SHA)
    missing_flag = {**adapter, "capabilities": {"read_only": True}}
    invalid_sha = rea_result_to_control_tower_decision(adapter, expected_sha="A" * 40)

    blocked = rea_result_to_control_tower_decision(missing_flag, expected_sha=SHA)
    assert blocked.gate_status == "BLOCKED"
    assert blocked.next_action == "HOLD"
    assert invalid_sha.gate_status == "BLOCKED"
    assert invalid_sha.next_action == "HOLD"
