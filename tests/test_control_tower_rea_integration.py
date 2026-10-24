from __future__ import annotations

from core.control_tower import ControlTower
from scripts.rea_review_candidates import build_review_candidates

SHA = "a" * 40


def _report(status="FINDINGS"):
    findings = [] if status == "PASS" else [{
        "finding_id": "0123456789abcdef",
        "category": "python_syntax",
        "severity": "MEDIUM",
        "target_sha": SHA,
        "evidence": {"path": "core/example.py", "line": 1, "check": "ast_parse_failed"},
    }]
    return {"schema_version": 1, "status": status, "target_sha": SHA,
            "complete": True, "findings_count": len(findings), "findings": findings}


def test_control_tower_exposes_read_only_rea_review_decision():
    candidates = build_review_candidates(_report(), expected_sha=SHA)
    decision = ControlTower().evaluate_rea_review_candidates(candidates, expected_sha=SHA)

    assert decision.reason_code == "rea_findings_review_required"
    assert decision.next_action == "OBSERVE_ONLY"
    assert decision.gate_status == "NOT_RUN"
    assert decision.task_template_id is None


def test_control_tower_blocks_sha_mismatch_and_never_selects_task():
    candidates = build_review_candidates(_report("PASS"), expected_sha=SHA)
    decision = ControlTower().evaluate_rea_review_candidates(candidates, expected_sha="b" * 40)

    assert decision.reason_code == "invalid_state"
    assert decision.next_action == "HOLD"
    assert decision.gate_status == "BLOCKED"
    assert decision.task_template_id is None
