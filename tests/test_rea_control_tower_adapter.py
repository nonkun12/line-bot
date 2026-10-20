from __future__ import annotations

from unittest.mock import patch

from scripts.rea_control_tower_adapter import prepare_rea_evidence, rea_evidence_is_valid_pass


SHA = "a" * 40


def report(*, status="PASS", findings=None, target_sha=SHA, complete=True):
    return {
        "status": status,
        "target_sha": target_sha,
        "complete": complete,
        "findings": findings or [],
        "findings_count": len(findings or []),
    }


def finding(severity="MEDIUM"):
    return {
        "finding_id": "a" * 16,
        "category": "python_syntax",
        "severity": severity,
        "evidence": {"path": "scripts/example.py", "line": 12},
    }


def test_rea_report_is_observation_only_and_sha_bound():
    with patch("scripts.rea_control_tower_adapter.scan_repository", return_value=report(
        status="FINDINGS", findings=[finding("MEDIUM")]
    )):
        result = prepare_rea_evidence(".", expected_sha=SHA)
    assert result["gate"] == "PASS"
    assert result["mode"] == "OBSERVE_ONLY"
    assert result["finding_count"] == 1
    assert result["blocking_count"] == 0
    assert result["execution_authorized"] is False
    assert result["patch_authorized"] is False
    assert result["hold_clear_authorized"] is False
    assert result["merge_deploy_authorized"] is False


def test_high_and_critical_findings_block_before_task_launch():
    for severity in ("HIGH", "CRITICAL"):
        with patch("scripts.rea_control_tower_adapter.scan_repository", return_value=report(
            status="FINDINGS", findings=[finding(severity)]
        )):
            result = prepare_rea_evidence(".", expected_sha=SHA)
        assert result["gate"] == "BLOCKED"
        assert result["reason_code"] == "rea_high_or_critical_finding"
        assert result["blocking_count"] == 1
        assert result["execution_authorized"] is False
        assert result["patch_authorized"] is False
        assert result["hold_clear_authorized"] is False
        assert result["merge_deploy_authorized"] is False


def test_sha_mismatch_and_incomplete_scan_block():
    with patch("scripts.rea_control_tower_adapter.scan_repository", return_value=report(target_sha="b" * 40)):
        mismatch = prepare_rea_evidence(".", expected_sha=SHA)
    assert mismatch["gate"] == "BLOCKED"
    assert mismatch["reason_code"] == "rea_sha_mismatch"

    with patch("scripts.rea_control_tower_adapter.scan_repository", return_value=report(complete=False, status="BLOCKED")):
        incomplete = prepare_rea_evidence(".", expected_sha=SHA)
    assert incomplete["gate"] == "BLOCKED"
    assert incomplete["reason_code"] == "rea_scan_incomplete"


def test_invalid_expected_sha_blocks_without_scanning():
    with patch("scripts.rea_control_tower_adapter.scan_repository") as scan:
        result = prepare_rea_evidence(".", expected_sha="not-a-sha")
    scan.assert_not_called()
    assert result["gate"] == "BLOCKED"
    assert result["reason_code"] == "expected_sha_invalid"



def test_execution_boundary_requires_complete_sha_bound_non_authorizing_pass():
    evidence = {
        "gate": "PASS",
        "mode": "OBSERVE_ONLY",
        "target_sha": SHA,
        "scanner_status": "PASS",
        "finding_count": 0,
        "findings_truncated": False,
        "critical_count": 0,
        "blocking_count": 0,
        "findings": [],
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    assert rea_evidence_is_valid_pass(evidence, expected_sha=SHA)

    assert not rea_evidence_is_valid_pass({**evidence, "target_sha": "b" * 40}, expected_sha=SHA)
    assert not rea_evidence_is_valid_pass({**evidence, "blocking_count": 1}, expected_sha=SHA)
    assert not rea_evidence_is_valid_pass({**evidence, "execution_authorized": True}, expected_sha=SHA)
    assert not rea_evidence_is_valid_pass(
        {**evidence, "findings": [{"severity": "HIGH"}], "finding_count": 1},
        expected_sha=SHA,
    )
    assert not rea_evidence_is_valid_pass(
        {key: value for key, value in evidence.items() if key != "blocking_count"},
        expected_sha=SHA,
    )



def test_execution_boundary_rejects_malformed_finding_schema_and_paths():
    base = {
        "gate": "PASS",
        "mode": "OBSERVE_ONLY",
        "target_sha": SHA,
        "scanner_status": "FINDINGS",
        "finding_count": 1,
        "critical_count": 0,
        "blocking_count": 0,
        "findings_truncated": False,
        "findings": [{
            "finding_id": "a" * 16,
            "category": "python_syntax",
            "severity": "MEDIUM",
            "path": "scripts/example.py",
            "line": 12,
            "status": "REVIEW_REQUIRED",
        }],
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    assert rea_evidence_is_valid_pass(base, expected_sha=SHA)

    bad_findings = [
        {**base["findings"][0], "finding_id": ""},
        {**base["findings"][0], "category": ""},
        {**base["findings"][0], "path": "../outside.py"},
        {**base["findings"][0], "path": "/tmp/outside.py"},
        {**base["findings"][0], "path": "scripts\\\\outside.py"},
        {**base["findings"][0], "line": True},
        {**base["findings"][0], "status": "PASS"},
        {**base["findings"][0], "unexpected": "value"},
    ]
    for bad in bad_findings:
        assert not rea_evidence_is_valid_pass(
            {**base, "findings": [bad]}, expected_sha=SHA
        )


def test_execution_boundary_rejects_inconsistent_counts_and_unknown_fields():
    base = {
        "gate": "PASS",
        "mode": "OBSERVE_ONLY",
        "target_sha": SHA,
        "scanner_status": "PASS",
        "finding_count": 0,
        "critical_count": 0,
        "blocking_count": 0,
        "findings_truncated": False,
        "findings": [],
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    assert rea_evidence_is_valid_pass(base, expected_sha=SHA)
    assert not rea_evidence_is_valid_pass({**base, "unexpected": 1}, expected_sha=SHA)
    assert not rea_evidence_is_valid_pass({**base, "finding_count": 1}, expected_sha=SHA)
    assert not rea_evidence_is_valid_pass({**base, "scanner_status": "FINDINGS"}, expected_sha=SHA)
    assert not rea_evidence_is_valid_pass(
        {**base, "finding_count": 101, "findings_truncated": True}, expected_sha=SHA
    )
    assert not rea_evidence_is_valid_pass(
        {**base, "finding_count": 101, "findings_truncated": True,
         "findings": [base["findings"]] * 100}, expected_sha=SHA
    )



def test_execution_boundary_accepts_well_formed_truncated_record():
    finding_record = {
        "finding_id": "a" * 16,
        "category": "python_syntax",
        "severity": "MEDIUM",
        "path": "scripts/example.py",
        "line": 12,
        "status": "REVIEW_REQUIRED",
    }
    evidence = {
        "gate": "PASS",
        "mode": "OBSERVE_ONLY",
        "target_sha": SHA,
        "scanner_status": "FINDINGS",
        "finding_count": 101,
        "critical_count": 0,
        "blocking_count": 0,
        "findings_truncated": True,
        "findings": [{**finding_record, "finding_id": f"{index:016x}"} for index in range(100)],
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    assert rea_evidence_is_valid_pass(evidence, expected_sha=SHA)
    malformed = {**evidence, "findings": [{**finding_record, "severity": []}] + evidence["findings"][1:]}
    assert not rea_evidence_is_valid_pass(malformed, expected_sha=SHA)
