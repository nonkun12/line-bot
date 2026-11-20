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


def test_handoff_binds_stop_and_hold_to_trusted_source_run_artifacts():
    workflow = (ROOT / ".github/workflows/rea-verification-handoff.yml").read_text()
    assert "control-tower-emergency-stop" in workflow
    assert "minimal-autonomous-loop-{source_run_id}" in workflow
    assert "recovery-ai-state-readback.json" in workflow
    assert 'record.get("held", False)' in workflow
    assert 'record.get("resume_requires_review", False)' in workflow
    assert 'stop_state = trusted_stop_state()' in workflow
    assert 'hold_state = trusted_hold_state(source_run_id, task_id)' in workflow


def test_handoff_does_not_use_receipt_stop_hold_claims_as_authority():
    workflow = (ROOT / ".github/workflows/rea-verification-handoff.yml").read_text()
    assert 'receipt.get("stop_state")' not in workflow
    assert 'receipt.get("hold_state")' not in workflow
    assert 'if stop_state != "INACTIVE"' in workflow
    assert 'elif hold_state != "CLEAR"' in workflow
