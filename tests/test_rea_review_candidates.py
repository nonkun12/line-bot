from __future__ import annotations

from scripts.rea_review_candidates import build_review_candidates


SHA = "a" * 40


def _report(*, status="FINDINGS", findings=None):
    rows = findings if findings is not None else [{
        "finding_id": "0123456789abcdef",
        "category": "python_syntax",
        "severity": "HIGH",
        "target_sha": SHA,
        "evidence": {"path": "core/example.py", "line": 12, "check": "ast_parse_failed"},
        "status": "REVIEW_REQUIRED",
    }]
    return {
        "schema_version": 1,
        "status": status,
        "target_sha": SHA,
        "complete": True,
        "findings_count": len(rows),
        "findings": rows,
    }


def test_rea_findings_become_advisory_candidates_without_execution_rights():
    result = build_review_candidates(_report(), expected_sha=SHA)

    assert result["status"] == "FINDINGS"
    assert result["next_action"] == "OBSERVE_ONLY"
    assert result["gate_status"] == "NOT_RUN"
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["status"] == "REVIEW_REQUIRED"
    assert result["candidates"][0]["task_template_id"] is None
    assert result["candidates"][0]["auto_approved"] is False
    assert result["capabilities"] == {
        "read_only": True,
        "auto_approval": False,
        "queue_mutation": False,
        "patch_merge_deploy": False,
    }


def test_clean_complete_rea_report_produces_no_candidates():
    result = build_review_candidates(_report(status="PASS", findings=[]), expected_sha=SHA)

    assert result["status"] == "PASS"
    assert result["gate_status"] == "PASS"
    assert result["candidate_count"] == 0
    assert result["candidates"] == []


def test_incomplete_or_wrong_sha_evidence_fails_closed():
    incomplete = _report()
    incomplete["complete"] = False
    wrong_sha = _report()
    wrong_sha["target_sha"] = "b" * 40

    for report in (incomplete, wrong_sha, _report()):
        result = build_review_candidates(report, expected_sha="c" * 40)
        assert result["status"] == "BLOCKED"
        assert result["next_action"] == "OBSERVE_ONLY"
        assert result["candidate_count"] == 0


def test_mixed_finding_sha_or_path_traversal_blocks_entire_report():
    wrong_finding_sha = _report()
    wrong_finding_sha["findings"][0]["target_sha"] = "b" * 40
    traversal = _report()
    traversal["findings"][0]["evidence"]["path"] = "core/../secret.py"

    for report in (wrong_finding_sha, traversal):
        result = build_review_candidates(report, expected_sha=SHA)
        assert result["status"] == "BLOCKED"
        assert result["candidate_count"] == 0


def test_inconsistent_report_count_or_status_blocks_entire_report():
    bad_count = _report()
    bad_count["findings_count"] = 2
    bad_status = _report(status="PASS")

    for report in (bad_count, bad_status):
        result = build_review_candidates(report, expected_sha=SHA)
        assert result["status"] == "BLOCKED"
        assert result["candidate_count"] == 0


def test_bad_expected_sha_and_non_object_report_fail_closed():
    assert build_review_candidates({}, expected_sha="not-a-sha")["status"] == "BLOCKED"
    assert build_review_candidates([], expected_sha=SHA)["status"] == "BLOCKED"


def test_boolean_schema_version_and_count_are_not_accepted_as_integers():
    bad_schema = _report()
    bad_schema["schema_version"] = True
    bad_count = _report()
    bad_count["findings_count"] = True

    for report in (bad_schema, bad_count):
        result = build_review_candidates(report, expected_sha=SHA)
        assert result["status"] == "BLOCKED"
        assert result["candidate_count"] == 0
