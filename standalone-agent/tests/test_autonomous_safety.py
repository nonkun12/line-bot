import os

from agents.patch.apply import apply_patch, _protected_paths
from graph.graph import route_from_review


def test_protected_paths_reject_secret_and_runtime_files(tmp_path):
    patch = """diff --git a/.env b/.env
--- a/.env
+++ b/.env
@@ -1 +1 @@
-OLD
+SECRET
"""
    assert ".env" in _protected_paths(patch)
    result = apply_patch(patch, str(tmp_path))
    assert result["applied"] is False
    assert result["error"] == "protected path change rejected"


def test_application_files_are_not_blocked_by_default():
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-OLD
+NEW
"""
    assert _protected_paths(patch) == []


def test_review_failure_routes_to_fix_only_for_retryable_ai_review():
    assert route_from_review({
        "review_result": {
            "status": "failed",
            "retryable": True,
            "ai_review": {"verdict": "FAIL"},
        },
    }) == "fix_agent"


def test_non_retryable_review_failure_stops():
    assert route_from_review({
        "review_result": {
            "status": "failed",
            "retryable": False,
            "ai_review": {"verdict": "FAIL"},
        },
    }) == "finalizer"
