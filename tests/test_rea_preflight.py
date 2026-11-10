from scripts.rea_preflight import evaluate_rea, require_rea_pass


def test_evaluate_rea_returns_sha_bound_evidence(monkeypatch, tmp_path):
    import subprocess
    from scripts import rea_preflight

    monkeypatch.setattr(
        rea_preflight.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "a" * 40 + "\\n", ""),
    )
    expected = {"gate": "PASS", "target_sha": "a" * 40}
    monkeypatch.setattr(rea_preflight, "prepare_rea_evidence", lambda root, expected_sha: expected)
    assert evaluate_rea(tmp_path) == expected


def test_evaluate_rea_fails_closed_when_head_unavailable(monkeypatch, tmp_path):
    from scripts import rea_preflight

    monkeypatch.setattr(
        rea_preflight.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unavailable")),
    )
    assert evaluate_rea(tmp_path) == {
        "gate": "BLOCKED",
        "reason_code": "rea_head_unavailable",
    }


def test_require_rea_pass_raises_on_blocked_evidence(monkeypatch, tmp_path):
    from scripts import rea_preflight

    monkeypatch.setattr(
        rea_preflight,
        "evaluate_rea",
        lambda root: {"gate": "BLOCKED", "reason_code": "rea_scan_incomplete"},
    )
    import pytest
    with pytest.raises(RuntimeError, match="REA preflight blocked"):
        require_rea_pass(tmp_path)
