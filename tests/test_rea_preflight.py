from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import rea_preflight


SHA = "a" * 40


def valid_evidence():
    return {
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


def test_require_rea_pass_accepts_sha_bound_valid_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(
        rea_preflight.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"{SHA}\n"),
    )
    evidence = valid_evidence()
    monkeypatch.setattr(rea_preflight, "prepare_rea_evidence", lambda root, expected_sha: evidence)
    monkeypatch.setattr(rea_preflight, "rea_evidence_is_valid_pass", lambda value, expected_sha: value is evidence and expected_sha == SHA)

    assert rea_preflight.require_rea_pass(tmp_path) is evidence


def test_require_rea_pass_blocks_scanner_findings(monkeypatch, tmp_path):
    monkeypatch.setattr(
        rea_preflight.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"{SHA}\n"),
    )
    monkeypatch.setattr(
        rea_preflight,
        "prepare_rea_evidence",
        lambda root, expected_sha: {"gate": "BLOCKED", "reason_code": "rea_high_or_critical_finding"},
    )

    with pytest.raises(RuntimeError, match="REA_BLOCKED"):
        rea_preflight.require_rea_pass(tmp_path)


def test_require_rea_pass_blocks_missing_head_sha(monkeypatch, tmp_path):
    monkeypatch.setattr(
        rea_preflight.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    with pytest.raises(RuntimeError, match="head_sha_unavailable"):
        rea_preflight.require_rea_pass(tmp_path)


def test_require_rea_pass_blocks_invalid_pass_schema(monkeypatch, tmp_path):
    monkeypatch.setattr(
        rea_preflight.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"{SHA}\n"),
    )
    evidence = valid_evidence()
    monkeypatch.setattr(rea_preflight, "prepare_rea_evidence", lambda root, expected_sha: evidence)
    monkeypatch.setattr(rea_preflight, "rea_evidence_is_valid_pass", lambda value, expected_sha: False)

    with pytest.raises(RuntimeError, match="rea_pass_evidence_invalid"):
        rea_preflight.require_rea_pass(tmp_path)
