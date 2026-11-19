from __future__ import annotations

import hashlib
import json

from core.rea_candidate_gate import validate_candidate_publication

BASE = "a" * 40
HEAD = "b" * 40
TASK = "task-001"
PATHS = ["core/example.py"]


def valid_inputs():
    row = {
        "task_id": TASK, "status": "BLOCKED", "exit_code": 1,
        "failure_reason": "rea_artifact_hold", "base_sha": BASE, "produced_sha": HEAD,
        "rea_artifact": {
            "status": "HOLD", "reason_code": "verification_incomplete",
            "tests": "UNKNOWN", "risk": "MEDIUM", "diff_scan": "PASS",
            "stop_state": "INACTIVE", "hold_state": "CLEAR", "changed_file_count": 1,
            "execution_authorized": False, "patch_authorized": False,
            "hold_clear_authorized": False, "merge_deploy_authorized": False,
        },
        "recovery_ai": {
            "recorded": True, "status": "BLOCKED",
            "decision": {"action": "HOLD"},
        },
        "control_tower": {
            "recorded": True,
            "orchestration": {
                "phase": "STOP", "next_action": "REPORT_BLOCKED",
                "reason_code": "execution_not_completed", "allow_continue": False,
                "repair_executed": False,
            },
        },
        "execution_approval": {
            "gate": "PASS", "execution_authorized": True, "scope": "execution",
            "actor": "nonkun12", "task_id": TASK, "base_sha": BASE,
            "instruction_sha256": "c" * 64, "allowed_paths_sha256": "d" * 64,
            "consumption": {
                "gate": "PASS", "reason_code": "approval_consumed_once",
                "marker_ref": "refs/heads/rsi-approval-consumed/" + "e" * 64,
                "marker_sha": BASE,
            },
        },
    }
    task = {"id": TASK, "instruction": "Add a bounded test", "allowed_paths": PATHS}
    allowed_digest = hashlib.sha256(json.dumps(sorted(PATHS), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    row["instruction_sha256"] = "f" * 64
    row["allowed_paths_sha256"] = allowed_digest
    row["execution_approval"]["allowed_paths_sha256"] = allowed_digest
    row["execution_approval"]["instruction_sha256"] = "f" * 64
    catalog_task = {**task, "execution_approved": True}
    return [row], {"tasks": [task]}, {"tasks": [catalog_task]}


def validate(rows=None, queue=None, catalog=None, paths=PATHS):
    default_rows, default_queue, default_catalog = valid_inputs()
    return validate_candidate_publication(
        default_rows if rows is None else rows,
        default_queue if queue is None else queue,
        default_catalog if catalog is None else catalog,
        expected_base_sha=BASE, observed_head_sha=HEAD, changed_paths=paths,
    )


def test_single_explicitly_approved_task_can_publish_candidate_only():
    result = validate()
    assert result["allowed"] is True
    assert result["status"] == "PASS"
    assert result["merge_deploy_authorized"] is False


def test_missing_or_replayed_approval_blocks_candidate():
    rows, _, _ = valid_inputs()
    rows[0]["execution_approval"]["consumption"]["gate"] = "BLOCKED"
    assert validate(rows=rows)["reason_code"] == "candidate_execution_approval_invalid"


def test_candidate_requires_independent_verification_only_hold():
    rows, _, _ = valid_inputs()
    rows[0]["failure_reason"] = "some_other_failure"
    assert validate(rows=rows)["reason_code"] == "candidate_not_blocked_only_by_independent_verification"


def test_high_risk_or_unknown_risk_never_enters_candidate_queue():
    rows, _, _ = valid_inputs()
    rows[0]["rea_artifact"]["risk"] = "HIGH"
    assert validate(rows=rows)["reason_code"] == "candidate_rea_conditions_not_met"


def test_stop_hold_and_path_allowlist_are_mandatory():
    rows, _, _ = valid_inputs()
    rows[0]["rea_artifact"]["stop_state"] = "ACTIVE"
    assert validate(rows=rows)["reason_code"] == "candidate_rea_conditions_not_met"
    assert validate(paths=["core/other.py"])["reason_code"] == "candidate_changed_paths_outside_allowlist"


def test_catalog_approval_and_exact_sha_are_mandatory():
    rows, queue, catalog = valid_inputs()
    catalog["tasks"][0]["execution_approved"] = False
    assert validate(rows=rows, queue=queue, catalog=catalog)["reason_code"] == "candidate_task_definition_not_approved"
    assert validate_candidate_publication(
        rows, queue, catalog, expected_base_sha=BASE, observed_head_sha=BASE, changed_paths=PATHS
    )["reason_code"] == "candidate_has_no_commit"


def test_candidate_requires_recovery_ai_and_control_tower_to_record_the_stop():
    rows, _, _ = valid_inputs()
    rows[0].pop("recovery_ai")
    assert validate(rows=rows)["reason_code"] == "candidate_recovery_ai_stop_evidence_missing"
    rows, _, _ = valid_inputs()
    rows[0]["control_tower"]["orchestration"]["allow_continue"] = True
    assert validate(rows=rows)["reason_code"] == "candidate_control_tower_stop_evidence_missing"


def test_candidate_rejects_mismatched_instruction_or_path_digests():
    rows, _, _ = valid_inputs()
    rows[0]["instruction_sha256"] = "9" * 64
    assert validate(rows=rows)["reason_code"] == "candidate_execution_approval_invalid"
    rows, _, _ = valid_inputs()
    rows[0]["execution_approval"]["allowed_paths_sha256"] = "8" * 64
    assert validate(rows=rows)["reason_code"] == "candidate_execution_approval_invalid"


def test_multiple_task_rows_are_not_combined_into_one_candidate():
    rows, queue, catalog = valid_inputs()
    assert validate(rows=rows * 2, queue=queue, catalog=catalog)["reason_code"] == "candidate_requires_exactly_one_task"


def test_approval_summary_is_sanitized():
    from scripts.run_minimal_autonomous_loop import _sanitized_execution_approval

    value = {
        "gate": "PASS", "reason_code": "authenticated_workflow_dispatch_approval",
        "execution_authorized": True, "scope": "execution", "actor": "nonkun12",
        "task_id": TASK, "instruction_sha256": "c" * 64,
        "allowed_paths_sha256": "d" * 64, "base_sha": BASE,
        "secret": "must-not-copy",
        "consumption": {
            "gate": "PASS", "reason_code": "approval_consumed_once",
            "marker_ref": "refs/heads/rsi-approval-consumed/" + "e" * 64,
            "marker_sha": BASE, "token": "must-not-copy",
        },
    }
    result = _sanitized_execution_approval(value)
    assert result is not None
    assert "secret" not in result
    assert "token" not in result["consumption"]
    assert result["consumption"]["marker_sha"] == BASE
