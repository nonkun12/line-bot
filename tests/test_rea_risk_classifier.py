from __future__ import annotations

from core.rea_risk_classifier import classify_changed_paths


def test_docs_only_is_low():
    assert classify_changed_paths(["README.md", "docs/architecture.rst"]) == {
        "risk": "LOW", "reason_code": "documentation_only"
    }


def test_application_and_test_code_are_medium():
    assert classify_changed_paths(["core/worker.py", "tests/test_worker.py"]) == {
        "risk": "MEDIUM", "reason_code": "application_or_test_code"
    }


def test_workflow_and_security_sensitive_paths_are_high():
    assert classify_changed_paths([".github/workflows/ci.yml"])["risk"] == "HIGH"
    assert classify_changed_paths(["core/emergency_stop.py"])["risk"] == "HIGH"
    assert classify_changed_paths(["requirements.txt"])["risk"] == "HIGH"


def test_unsafe_and_unknown_paths_never_become_low():
    assert classify_changed_paths(["../outside.py"])["risk"] == "HIGH"
    assert classify_changed_paths(["assets/model.bin"])["risk"] == "UNKNOWN"


def test_missing_paths_are_unknown():
    assert classify_changed_paths([])["risk"] == "UNKNOWN"
    assert classify_changed_paths(None)["risk"] == "UNKNOWN"
