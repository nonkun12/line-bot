from __future__ import annotations

from core.rea_artifact_evaluator import evaluate_artifact_evidence


BASE = "1" * 40
HEAD = "2" * 40


def evidence(**overrides):
    value = {
        "task_id": "task-001",
        "base_sha": BASE,
        "head_sha": HEAD,
        "changed_files": ["core/example.py"],
        "tests": "PASS",
        "diff_scan": "PASS",
        "risk": "MEDIUM",
        "stop_state": "INACTIVE",
        "hold_state": "CLEAR",
    }
    value.update(overrides)
    return value


def test_complete_evidence_passes_without_authority():
    result = evaluate_artifact_evidence(evidence())
    assert result["status"] == "PASS"
    assert result["reason_code"] == "artifact_evidence_verified"
    assert result["evidence_sha256"]
    assert result["execution_authorized"] is False
    assert result["patch_authorized"] is False
    assert result["hold_clear_authorized"] is False
    assert result["merge_deploy_authorized"] is False


def test_missing_evidence_holds_even_with_extra_keys():
    result = evaluate_artifact_evidence(evidence(base_sha=None, extra="not evidence"))
    assert result["status"] == "HOLD"
    assert result["reason_code"] == "commit_identity_invalid"


def test_missing_required_key_holds():
    value = evidence()
    del value["diff_scan"]
    result = evaluate_artifact_evidence(value)
    assert result["status"] == "HOLD"
    assert result["reason_code"] == "required_evidence_missing"


def test_stop_and_hold_fail_closed():
    assert evaluate_artifact_evidence(evidence(stop_state="ACTIVE"))["status"] == "BLOCKED"
    assert evaluate_artifact_evidence(evidence(hold_state="UNKNOWN"))["status"] == "BLOCKED"


def test_high_and_unknown_risk_do_not_pass():
    assert evaluate_artifact_evidence(evidence(risk="HIGH"))["status"] == "BLOCKED"
    assert evaluate_artifact_evidence(evidence(risk="UNKNOWN"))["status"] == "HOLD"


def test_failed_verification_fails():
    assert evaluate_artifact_evidence(evidence(tests="FAIL"))["status"] == "FAIL"
    assert evaluate_artifact_evidence(evidence(diff_scan="FAIL"))["status"] == "FAIL"


def test_incomplete_verification_holds():
    assert evaluate_artifact_evidence(evidence(tests="NOT_RUN"))["status"] == "HOLD"
    assert evaluate_artifact_evidence(evidence(diff_scan="UNKNOWN"))["status"] == "HOLD"


def test_no_change_is_distinct():
    result = evaluate_artifact_evidence(evidence(base_sha=BASE, head_sha=BASE, changed_files=[]))
    assert result["status"] == "NO_CHANGE"


def test_changed_files_without_new_commit_holds():
    result = evaluate_artifact_evidence(evidence(base_sha=BASE, head_sha=BASE))
    assert result["status"] == "HOLD"

def test_malformed_value_types_hold_without_crashing():
    assert evaluate_artifact_evidence(evidence(tests=[]))["status"] == "HOLD"
    assert evaluate_artifact_evidence(evidence(risk={}))["status"] == "HOLD"


def test_runtime_summary_adapter_requires_explicit_independent_evidence():
    from core.rea_artifact_evaluator import evaluate_runtime_summary

    summary = {
        "task_id": "task-001",
        "base_sha": BASE,
        "produced_sha": HEAD,
        "post_generation_rea": {"status": "PASS"},
    }
    result = evaluate_runtime_summary(summary, {"changed_files": ["tests/test_example.py"]})
    assert result["status"] == "HOLD"
    assert result["reason_code"] == "stop_active_or_unverified"
    assert result["execution_authorized"] is False


def test_runtime_summary_adapter_passes_only_with_all_explicit_evidence():
    from core.rea_artifact_evaluator import evaluate_runtime_summary

    summary = {
        "task_id": "task-001",
        "base_sha": BASE,
        "produced_sha": HEAD,
        "post_generation_rea": {"status": "PASS"},
    }
    verification = {
        "changed_files": ["tests/test_example.py"],
        "tests": "PASS",
        "risk": "LOW",
        "stop_state": "INACTIVE",
        "hold_state": "CLEAR",
    }
    result = evaluate_runtime_summary(summary, verification)
    assert result["status"] == "PASS"
    assert result["reason_code"] == "artifact_evidence_verified"
    assert result["merge_deploy_authorized"] is False
