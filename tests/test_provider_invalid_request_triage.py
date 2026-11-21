import pytest

from core.loop_failure_codes import extract_safe_failure_code, failure_code_category
from scripts.maintenance_ai import build_report


def test_bad_request_invalid_request_is_provider_error_not_invalid_task():
    detail = "append_only_test_generation_failed:BadRequestError:status=400:code=invalid_request:param=max_tokens"
    code = extract_safe_failure_code(detail)
    assert code == "provider_request_invalid"
    assert failure_code_category(code) == "provider_error"


def test_http_400_without_explicit_invalid_request_code_stays_unclassified():
    assert extract_safe_failure_code("provider response status=400") is None


def test_provider_error_gets_specific_maintenance_diagnosis_without_permissions():
    report = build_report([{
        "task_id": "provider-invalid-request",
        "status": "FAIL",
        "failure_reason": "task_runtime_failed",
        "failure_code": "provider_request_invalid",
        "recovery_ai": {"decision": {"action": "HOLD", "requires_human": True}},
    }])
    diagnosis = report["diagnoses"][0]
    assert report["status"] == "REVIEW_REQUIRED"
    assert diagnosis["category"] == "provider_error"
    assert diagnosis["requires_human"] is True
    assert "do not retry automatically" in diagnosis["recommendation"]
    assert all(value is False for value in diagnosis["permissions"].values())
