"""Regression tests for the local fm recovery advisor safety boundary."""
import json
import subprocess

from scripts.fm_recovery_advisor import _SCHEMA, advise, sanitize_incident


def test_sanitize_accepts_only_allowlisted_incident_metadata():
    safe = sanitize_incident({
        "task_id": "task-123",
        "category": "test_regression",
        "run_status": "failure",
        "failing_tests": ["tests/test_loop.py::test_gate"],
    })
    assert safe["task_id"] == "task-123"
    assert safe["failing_tests"] == ["tests/test_loop.py::test_gate"]


def test_sanitize_rejects_raw_logs_and_unknown_fields():
    result = advise({"task_id": "task-123", "raw_error": "token=secret"}, executable="/fake/fm")
    assert result["status"] == "REJECTED"
    assert "secret" not in json.dumps(result)


def test_missing_fm_fails_closed():
    result = advise({"task_id": "task-123"}, executable="/definitely/not/a/real/fm")
    # subprocess raises OSError; it must never be treated as a recovery success.
    assert result["status"] == "UNAVAILABLE"


def test_advice_is_never_authoritative(monkeypatch):
    payload = json.dumps({
        "suggested_category": "test_regression",
        "summary": "Inspect the failing test and its assertion.",
        "checks": ["Review the test diff."],
    })

    def fake_run(*args, **kwargs):
        kwargs["stdout"].write(payload.encode("utf-8"))
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("scripts.fm_recovery_advisor.subprocess.run", fake_run)
    result = advise({"task_id": "task-123"}, executable="/fake/fm")
    assert result["status"] == "ADVISORY_ONLY"
    assert result["authority"] == "none"
    assert result["patch_allowed"] is False
    assert result["merge_allowed"] is False
    assert result["deploy_allowed"] is False


def test_invalid_model_output_fails_closed(monkeypatch):
    def fake_run(*args, **kwargs):
        kwargs["stdout"].write(b'{"suggested_category":"unknown","summary":"ok","checks":[],"action":"deploy"}')
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("scripts.fm_recovery_advisor.subprocess.run", fake_run)
    result = advise({"task_id": "task-123"}, executable="/fake/fm")
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "fm_output_invalid"



def test_malformed_category_type_fails_closed(monkeypatch):
    def fake_run(*args, **kwargs):
        kwargs["stdout"].write(
            b'{"suggested_category":[],"summary":"ok","checks":[]}'
        )
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("scripts.fm_recovery_advisor.subprocess.run", fake_run)
    result = advise({"task_id": "task-123"}, executable="/fake/fm")
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "fm_output_invalid"


def test_timeout_is_bounded_and_fail_closed(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr("scripts.fm_recovery_advisor.subprocess.run", fake_run)
    result = advise({"task_id": "task-123"}, executable="/fake/fm", timeout=3)
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "fm_timeout"


def test_fm_schema_has_required_field_order_extension():
    assert _SCHEMA["x-order"] == ["suggested_category", "summary", "checks"]
