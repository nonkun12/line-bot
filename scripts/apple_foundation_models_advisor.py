"""Optional local advisor backed by Apple's on-device Foundation Models CLI.

This adapter is advisory only: its output must never determine PASS/FAIL, retries,
patch application, task resumption, merge, or deployment. The deterministic
Recovery AI controller and existing Safety Gate remain authoritative.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterable


TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
TEST_ID_RE = re.compile(r"^[A-Za-z0-9_./:\\[\\] -]{1,180}$")
ALLOWED_CATEGORIES = frozenset({
    "network_transient", "service_unavailable", "rate_limited",
    "test_regression", "timeout", "process_crash", "invalid_task",
    "invalid_evidence", "security_violation", "state_persistence_failure", "unknown",
})
MAX_TESTS = 20
MAX_OUTPUT_CHARS = 1600


@dataclass(frozen=True)
class AdvisorResult:
    available: bool
    advice: str = ""
    reason: str = ""


def _safe_metadata(task_id: str, category: str, failing_tests: Iterable[str]) -> dict:
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        raise ValueError("invalid task ID")
    if category not in ALLOWED_CATEGORIES:
        category = "unknown"
    tests = []
    for item in failing_tests:
        value = str(item).strip().replace("\\", "/")
        if value and len(value) <= 180 and TEST_ID_RE.fullmatch(value):
            tests.append(value)
        if len(tests) >= MAX_TESTS:
            break
    return {"task_id": task_id, "category": category, "failing_tests": sorted(set(tests))}


def _minimal_environment() -> dict[str, str]:
    """Pass only basic user-session variables; never forward API keys or app secrets."""
    allowed = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
    env = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    env.setdefault("PATH", "/usr/bin:/bin")
    return env


def advise(task_id: str, category: str, failing_tests: Iterable[str] = (), *, timeout_seconds: int = 20) -> AdvisorResult:
    """Ask local fm CLI for bounded diagnostic suggestions; fail closed to no advice."""
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 30:
        raise ValueError("timeout_seconds must be between 1 and 30")
    metadata = _safe_metadata(task_id, category, failing_tests)
    executable = shutil.which("fm")
    if not executable:
        return AdvisorResult(False, reason="fm_cli_unavailable")

    prompt = (
        "You are a read-only diagnostic advisor. Analyze only this sanitized metadata. "
        "Return one short JSON object with a single string field 'advice' (maximum 500 characters). "
        "Suggest checks only. Do not claim tests passed, do not choose PASS/FAIL, do not request "
        "credentials, do not suggest running commands, editing files, resuming tasks, merging, or deploying. "
        "If evidence is insufficient, say so. Metadata: "
        + json.dumps(metadata, ensure_ascii=True, separators=(",", ":"))
    )
    try:
        completed = subprocess.run(
            [executable, "respond", prompt],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=_minimal_environment(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return AdvisorResult(False, reason="fm_execution_failed")
    if completed.returncode != 0:
        return AdvisorResult(False, reason="fm_nonzero_exit")

    raw = (completed.stdout or "").strip()
    if not raw or len(raw) > MAX_OUTPUT_CHARS:
        return AdvisorResult(False, reason="fm_output_invalid")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return AdvisorResult(False, reason="fm_output_not_json")
    if not isinstance(payload, dict) or set(payload) != {"advice"}:
        return AdvisorResult(False, reason="fm_output_schema_invalid")
    advice = payload.get("advice")
    if not isinstance(advice, str) or not advice.strip() or len(advice) > 500:
        return AdvisorResult(False, reason="fm_advice_invalid")
    return AdvisorResult(True, advice=advice.strip(), reason="advisory_only")
