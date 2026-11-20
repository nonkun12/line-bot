from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_independent_workflow_invokes_sha_bound_worker_without_stop_or_hold_overrides():
    workflow = (ROOT / ".github/workflows/rea-independent-verification.yml").read_text()
    assert "python scripts/rea_independent_verifier.py" in workflow
    assert '--base-sha "$BASE_SHA"' in workflow
    assert '--target-sha "$TARGET_SHA"' in workflow
    assert '"stop_state": "UNKNOWN"' in workflow
    assert '"hold_state": "UNKNOWN"' in workflow


def test_handoff_requires_verified_stop_and_hold_before_review_required():
    workflow = (ROOT / ".github/workflows/rea-verification-handoff.yml").read_text()
    assert 'receipt.get("stop_state") != "INACTIVE"' in workflow
    assert 'receipt.get("hold_state") != "CLEAR"' in workflow
    assert 'receipt.get("diff_scan") != "PASS"' in workflow
    assert 'gate="REVIEW_REQUIRED"' in workflow
