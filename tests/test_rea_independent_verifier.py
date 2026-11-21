from __future__ import annotations

import subprocess
from types import SimpleNamespace

from scripts import rea_independent_verifier as verifier


BASE = "a" * 40
HEAD = "b" * 40


def _scan(paths):
    return {
        "status": "PASS",
        "complete": True,
        "changed_paths": paths,
        "diff_sha256": "c" * 64,
    }


def test_independent_verifier_runs_fixed_pytest_command_and_returns_metadata_only(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(verifier, "_git", lambda root, *args: HEAD if args[0] == "rev-parse" else "")
    monkeypatch.setattr(verifier, "scan_commit_diff", lambda *args, **kwargs: _scan(["tests/test_sample.py"]))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)
    result = verifier.collect_independent_verification(
        repo_root=tmp_path,
        base_sha=BASE,
        target_sha=HEAD,
        stop_state="INACTIVE",
        hold_state="CLEAR",
    )

    assert result["tests"] == "PASS"
    assert result["diff_scan"] == "PASS"
    assert result["risk"] == "LOW"
    assert result["changed_files"] == ["tests/test_sample.py"]
    assert calls[0][0][-3:] == ["-m", "pytest", "-q"]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    assert calls[0][1]["stdout"] == subprocess.DEVNULL
    assert calls[0][1]["stderr"] == subprocess.DEVNULL
    assert "execution_authorized" not in result


def test_independent_verifier_rejects_checkout_sha_mismatch_without_running_tests(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(verifier, "_git", lambda root, *args: "d" * 40)
    calls = []
    monkeypatch.setattr(verifier.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    result = verifier.collect_independent_verification(
        repo_root=tmp_path, base_sha=BASE, target_sha=HEAD
    )

    assert result["tests"] == "UNKNOWN"
    assert result["reason_code"] == "independent_verification_unavailable"
    assert calls == []


def test_independent_verifier_classifies_application_code_as_high_risk(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(verifier, "_git", lambda root, *args: HEAD if args[0] == "rev-parse" else "")
    monkeypatch.setattr(verifier, "scan_commit_diff", lambda *args, **kwargs: _scan(["core/runtime.py"]))
    monkeypatch.setattr(
        verifier.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0)
    )
    result = verifier.collect_independent_verification(
        repo_root=tmp_path, base_sha=BASE, target_sha=HEAD
    )

    assert result["risk"] == "HIGH"
    assert result["tests"] == "PASS"


def test_independent_verifier_does_not_claim_pass_on_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier, "_git", lambda root, *args: HEAD if args[0] == "rev-parse" else "")
    monkeypatch.setattr(verifier, "scan_commit_diff", lambda *args, **kwargs: _scan(["tests/test_sample.py"]))

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=600)

    monkeypatch.setattr(verifier.subprocess, "run", timeout)
    result = verifier.collect_independent_verification(
        repo_root=tmp_path, base_sha=BASE, target_sha=HEAD
    )

    assert result["tests"] == "UNKNOWN"
    assert result["reason_code"] == "independent_test_timeout"
