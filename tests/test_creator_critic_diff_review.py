import copy

import pytest

from scripts.creator_critic_diff_review import EvidenceInvalid, review_evidence


def _evidence():
    return {
        "schema_version": 1,
        "task_id": "task-123",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "allowed_paths": ["tests/test_example.py"],
        "changed_files": [{"path": "tests/test_example.py", "status": "modified"}],
        "diff_sha256": "c" * 64,
        "tests": {
            "exit_code": 0, "passed": 12, "failed": 0, "skipped": 1,
            "report_sha256": "d" * 64,
        },
        "rea": {
            "status": "PASS", "complete": True, "target_sha": "b" * 40,
            "findings_count": 0,
        },
    }


def test_pass_requires_matching_complete_test_and_rea_evidence():
    report = review_evidence(_evidence())
    assert report["verdict"] == "PASS"
    assert report["reason_codes"] == []
    assert report["head_sha"] == "b" * 40
    assert report["capabilities"]["semantic_code_review"] is False
    assert report["capabilities"]["authorizes_merge_or_deploy"] is False


@pytest.mark.parametrize(
    ("path", "status", "reason"),
    [
        ("core/unauthorized.py", "modified", "changed_file_outside_task_allowlist"),
        ("tests/test_example.py", "deleted", "changed_file_operation_not_allowed"),
        ("../outside.py", "modified", "changed_file_path_invalid_or_duplicate"),
        ("/absolute.py", "modified", "changed_file_path_invalid_or_duplicate"),
    ],
)
def test_scope_and_operation_violations_hold(path, status, reason):
    payload = _evidence()
    payload["changed_files"] = [{"path": path, "status": status}]
    if path.startswith("../") or path.startswith("/"):
        with pytest.raises(EvidenceInvalid):
            review_evidence(payload)
    else:
        report = review_evidence(payload)
        assert report["verdict"] == "HOLD"
        assert reason in report["reason_codes"]


def test_test_failure_or_missing_execution_evidence_holds():
    payload = _evidence()
    payload["tests"]["exit_code"] = 1
    payload["tests"]["failed"] = 1
    report = review_evidence(payload)
    assert report["verdict"] == "HOLD"
    assert "tests_not_proven_passing" in report["reason_codes"]


def test_rea_incomplete_findings_or_wrong_sha_holds():
    payload = _evidence()
    payload["rea"]["complete"] = False
    payload["rea"]["findings_count"] = 1
    payload["rea"]["target_sha"] = "e" * 40
    report = review_evidence(payload)
    assert report["verdict"] == "HOLD"
    assert "rea_not_clean_and_complete" in report["reason_codes"]
    assert "rea_target_sha_mismatch" in report["reason_codes"]


def test_malformed_or_extra_evidence_fails_closed():
    payload = _evidence()
    payload["unexpected"] = "ignored?"
    with pytest.raises(EvidenceInvalid):
        review_evidence(payload)


def test_duplicate_changed_paths_are_rejected():
    payload = _evidence()
    payload["changed_files"].append(copy.deepcopy(payload["changed_files"][0]))
    with pytest.raises(EvidenceInvalid):
        review_evidence(payload)


def test_deterministic_evidence_hash_is_stable():
    payload = _evidence()
    assert review_evidence(payload)["evidence_sha256"] == review_evidence(payload)["evidence_sha256"]
