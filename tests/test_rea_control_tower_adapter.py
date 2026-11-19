from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.rea_control_tower_adapter import (
    prepare_rea_evidence,
    publish_row_has_valid_gates,
    rea_evidence_is_valid_pass,
)

SHA = "a" * 40


def report(*, status="PASS", findings=None, target_sha=SHA, complete=True):
    return {"status": status, "target_sha": target_sha, "complete": complete,
            "findings": findings or [], "findings_count": len(findings or [])}


def finding(severity="MEDIUM", *, path="scripts/example.py", line=12):
    return {"finding_id": "a" * 16, "category": "python_syntax", "severity": severity,
            "evidence": {"path": path, "line": line}}


def safe_finding(index=0):
    return {"finding_id": f"{index:016x}", "category": "python_syntax",
            "severity": "MEDIUM", "path": "scripts/example.py", "line": 12,
            "status": "REVIEW_REQUIRED"}


def pass_evidence(findings=None, *, finding_count=None, truncated=False):
    findings = list(findings or [])
    if finding_count is None:
        finding_count = len(findings)
    return {
        "gate": "PASS", "mode": "OBSERVE_ONLY", "target_sha": SHA,
        "scanner_status": "FINDINGS" if finding_count else "PASS",
        "finding_count": finding_count, "findings_truncated": truncated,
        "critical_count": 0, "blocking_count": 0, "findings": findings,
        "execution_authorized": False, "patch_authorized": False,
        "hold_clear_authorized": False, "merge_deploy_authorized": False,
    }


def test_rea_report_is_observation_only_and_sha_bound():
    with patch("scripts.rea_control_tower_adapter.scan_repository",
               return_value=report(status="FINDINGS", findings=[finding()])):
        result = prepare_rea_evidence(".", expected_sha=SHA)
    assert result["gate"] == "PASS" and result["mode"] == "OBSERVE_ONLY"
    assert result["finding_count"] == 1 and result["blocking_count"] == 0
    for key in ("execution_authorized", "patch_authorized", "hold_clear_authorized", "merge_deploy_authorized"):
        assert result[key] is False


def test_high_and_critical_findings_block_before_task_launch():
    for severity in ("HIGH", "CRITICAL"):
        with patch("scripts.rea_control_tower_adapter.scan_repository",
                   return_value=report(status="FINDINGS", findings=[finding(severity)])):
            result = prepare_rea_evidence(".", expected_sha=SHA)
        assert result["gate"] == "BLOCKED"
        assert result["reason_code"] == "rea_high_or_critical_finding"
        assert result["blocking_count"] == 1
        for key in ("execution_authorized", "patch_authorized", "hold_clear_authorized", "merge_deploy_authorized"):
            assert result[key] is False


def test_sha_mismatch_and_incomplete_scan_block():
    with patch("scripts.rea_control_tower_adapter.scan_repository", return_value=report(target_sha="b" * 40)):
        mismatch = prepare_rea_evidence(".", expected_sha=SHA)
    assert mismatch["gate"] == "BLOCKED" and mismatch["reason_code"] == "rea_sha_mismatch"
    with patch("scripts.rea_control_tower_adapter.scan_repository",
               return_value=report(complete=False, status="BLOCKED")):
        incomplete = prepare_rea_evidence(".", expected_sha=SHA)
    assert incomplete["gate"] == "BLOCKED" and incomplete["reason_code"] == "rea_scan_incomplete"


def test_invalid_expected_sha_blocks_without_scanning():
    with patch("scripts.rea_control_tower_adapter.scan_repository") as scan:
        result = prepare_rea_evidence(".", expected_sha="not-a-sha")
    scan.assert_not_called()
    assert result["gate"] == "BLOCKED" and result["reason_code"] == "expected_sha_invalid"


def test_accepts_empty_and_valid_nontruncated_pass():
    assert rea_evidence_is_valid_pass(pass_evidence(), expected_sha=SHA)
    assert rea_evidence_is_valid_pass(pass_evidence([safe_finding(1), safe_finding(2)]), expected_sha=SHA)


def test_accepts_valid_100_item_truncated_pass():
    evidence = pass_evidence([safe_finding(i) for i in range(100)], finding_count=101, truncated=True)
    assert rea_evidence_is_valid_pass(evidence, expected_sha=SHA)


@pytest.mark.parametrize("field,value", [
    ("finding_id", None), ("finding_id", "bad"), ("category", None),
    ("category", "../escape"), ("path", None), ("path", "../scripts/example.py"),
    ("path", "/etc/passwd"), ("path", "scripts\\example.py"),
    ("path", "docs/example.py"), ("path", "scripts/../../outside.py"),
    ("path", "scripts/unsafe.exe"), ("path", "scripts/bad\x1b.py"),
    ("path", "scripts/" + "a" * 510 + ".py"),
    ("line", True), ("line", 0), ("line", -1), ("line", "12"),
    ("line", 10**30),
    ("status", None), ("severity", "HIGH"),
])
def test_malformed_finding_fields_fail_closed(field, value):
    item = safe_finding()
    item[field] = value
    assert not rea_evidence_is_valid_pass(pass_evidence([item]), expected_sha=SHA)


def test_missing_and_unexpected_finding_fields_fail_closed():
    item = safe_finding()
    del item["status"]
    assert not rea_evidence_is_valid_pass(pass_evidence([item]), expected_sha=SHA)
    item = safe_finding()
    item["extra"] = "unexpected"
    assert not rea_evidence_is_valid_pass(pass_evidence([item]), expected_sha=SHA)


def test_unexpected_top_level_field_fails_closed():
    evidence = pass_evidence()
    evidence["execution_override"] = True
    assert not rea_evidence_is_valid_pass(evidence, expected_sha=SHA)


@pytest.mark.parametrize("count,truncated,visible,status", [
    (1, True, 1, "FINDINGS"), (100, True, 100, "FINDINGS"),
    (101, False, 100, "FINDINGS"), (0, False, 1, "FINDINGS"),
    (1, False, 1, "PASS"), (0, False, 0, "FINDINGS"),
])
def test_inconsistent_counts_truncation_or_status_fail_closed(count, truncated, visible, status):
    evidence = pass_evidence([safe_finding(i) for i in range(visible)],
                             finding_count=count, truncated=truncated)
    evidence["scanner_status"] = status
    assert not rea_evidence_is_valid_pass(evidence, expected_sha=SHA)


def test_bad_sha_aggregates_and_authority_flags_fail_closed():
    evidence = pass_evidence()
    assert not rea_evidence_is_valid_pass({**evidence, "target_sha": "b" * 40}, expected_sha=SHA)
    assert not rea_evidence_is_valid_pass({**evidence, "blocking_count": 1}, expected_sha=SHA)
    assert not rea_evidence_is_valid_pass({**evidence, "execution_authorized": True}, expected_sha=SHA)
    assert not rea_evidence_is_valid_pass({k: v for k, v in evidence.items() if k != "blocking_count"}, expected_sha=SHA)
    assert not rea_evidence_is_valid_pass(evidence, expected_sha="bad-sha")


@pytest.mark.parametrize("bad_value", [[], {}, None, ["HIGH"]])
def test_prepare_rea_evidence_malformed_severity_returns_blocked_not_exception(bad_value):
    malformed = finding()
    malformed["severity"] = bad_value
    with patch("scripts.rea_control_tower_adapter.scan_repository",
               return_value=report(status="FINDINGS", findings=[malformed])):
        result = prepare_rea_evidence(".", expected_sha=SHA)
    assert result["gate"] == "BLOCKED"
    assert result["reason_code"] == "rea_finding_schema_invalid"


@pytest.mark.parametrize("bad_value", [[], {}, None, ["PASS"]])
def test_prepare_rea_evidence_malformed_scanner_status_returns_blocked_not_exception(bad_value):
    with patch("scripts.rea_control_tower_adapter.scan_repository",
               return_value=report(status=bad_value)):
        result = prepare_rea_evidence(".", expected_sha=SHA)
    assert result["gate"] == "BLOCKED"
    assert result["reason_code"] == "rea_scanner_status_invalid"


@pytest.mark.parametrize("bad_value", [[], {}, None, ["PASS"]])
def test_pass_validator_malformed_scanner_status_returns_false_not_exception(bad_value):
    evidence = pass_evidence()
    evidence["scanner_status"] = bad_value
    assert not rea_evidence_is_valid_pass(evidence, expected_sha=SHA)


@pytest.mark.parametrize("bad_value", [[], {}, None, ["MEDIUM"]])
def test_pass_validator_malformed_severity_returns_false_not_exception(bad_value):
    item = safe_finding()
    item["severity"] = bad_value
    assert not rea_evidence_is_valid_pass(pass_evidence([item]), expected_sha=SHA)


@pytest.mark.parametrize("bad_report", [[], None, "not-an-object"])
def test_prepare_rea_evidence_non_object_report_returns_blocked(bad_report):
    with patch("scripts.rea_control_tower_adapter.scan_repository", return_value=bad_report):
        result = prepare_rea_evidence(".", expected_sha=SHA)
    assert result["gate"] == "BLOCKED"
    assert result["reason_code"] == "rea_report_invalid"



def _valid_publish_row():
    return {
        "task_id": "task-a",
        "status": "PASS",
        "exit_code": 0,
        "base_sha": SHA,
        "produced_sha": "b" * 40,
        "run_nonce": "d" * 32,
        "rea": pass_evidence(),
        "recovery_ai": {
            "recorded": True, "verified": True, "status": "PASS",
            "evidence": {
                "task_id": "task-a", "base_sha": SHA,
                "produced_sha": "b" * 40, "run_nonce": "d" * 32,
            },
        },
        "control_tower": {
            "recorded": True,
            "orchestration": {
                "phase": "REPORT",
                "next_action": "REPORT_VERIFIED_SUCCESS",
                "reason_code": "verified_success",
                "allow_continue": True,
                "task_id": "task-a",
                "repair_executed": False,
            },
        },
    }


def test_independent_publish_gate_requires_complete_exact_run_evidence():
    assert publish_row_has_valid_gates(_valid_publish_row(), expected_sha=SHA)


@pytest.mark.parametrize("mutate", [
    "missing_rea",
    "invalid_rea",
    "missing_recovery_evidence",
    "mismatched_recovery_evidence",
    "recovery_not_verified",
    "invalid_nonce",
    "missing_control_tower",
    "observation_not_recorded",
    "missing_orchestration",
    "orchestration_false",
    "orchestration_truthy_non_bool",
    "wrong_reason",
    "wrong_task_id",
    "wrong_phase",
    "missing_run_identity",
    "base_sha_mismatch",
    "no_change_sha_mismatch",
    "boolean_exit_code",
    "invalid_status",
])
def test_independent_publish_gate_fails_closed(mutate):
    row = _valid_publish_row()
    if mutate == "missing_rea":
        row.pop("rea")
    elif mutate == "invalid_rea":
        row["rea"]["target_sha"] = "c" * 40
    elif mutate == "missing_recovery_evidence":
        row.pop("recovery_ai")
    elif mutate == "mismatched_recovery_evidence":
        row["recovery_ai"]["evidence"]["task_id"] = "task-b"
    elif mutate == "recovery_not_verified":
        row["recovery_ai"]["verified"] = False
    elif mutate == "invalid_nonce":
        row["run_nonce"] = "not-a-nonce"
    elif mutate == "missing_control_tower":
        row.pop("control_tower")
    elif mutate == "observation_not_recorded":
        row["control_tower"]["recorded"] = False
    elif mutate == "missing_orchestration":
        row["control_tower"].pop("orchestration")
    elif mutate == "orchestration_false":
        row["control_tower"]["orchestration"]["allow_continue"] = False
    elif mutate == "orchestration_truthy_non_bool":
        row["control_tower"]["orchestration"]["allow_continue"] = 1
    elif mutate == "wrong_reason":
        row["control_tower"]["orchestration"]["reason_code"] = "unknown"
    elif mutate == "wrong_task_id":
        row["control_tower"]["orchestration"]["task_id"] = "task-b"
    elif mutate == "wrong_phase":
        row["control_tower"]["orchestration"]["phase"] = "RECOVER"
    elif mutate == "missing_run_identity":
        row.pop("produced_sha")
    elif mutate == "base_sha_mismatch":
        row["base_sha"] = "c" * 40
    elif mutate == "no_change_sha_mismatch":
        row["status"] = "NO_CHANGE"
    elif mutate == "boolean_exit_code":
        row["exit_code"] = False
    elif mutate == "invalid_status":
        row["status"] = "SUCCESS"
    assert not publish_row_has_valid_gates(row, expected_sha=SHA)


def test_independent_publish_gate_rejects_non_object_rows():
    assert not publish_row_has_valid_gates(None, expected_sha=SHA)
    assert not publish_row_has_valid_gates([], expected_sha=SHA)

def test_duplicate_finding_ids_fail_closed():
    first = safe_finding(1)
    second = safe_finding(1)
    assert not rea_evidence_is_valid_pass(pass_evidence([first, second]), expected_sha=SHA)


def test_prepare_rea_evidence_duplicate_finding_ids_block():
    with patch("scripts.rea_control_tower_adapter.scan_repository",
               return_value=report(status="FINDINGS", findings=[finding(), finding()])):
        result = prepare_rea_evidence(".", expected_sha=SHA)
    assert result["gate"] == "BLOCKED"
    assert result["reason_code"] == "rea_finding_schema_invalid"
