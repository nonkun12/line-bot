from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_unified_loop_worker_is_permanently_inert():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    worker = workflow.split("\n  minimal-loop:", 1)[1]
    assert "needs: safety-preflight" in worker
    assert "needs.safety-preflight.outputs.execution_enabled == 'true' && false" in worker
    assert "python scripts/run_minimal_autonomous_loop.py" in worker
    assert "AUTO_APPLY_PATCH: 'false'" in worker
    assert "AUTO_DEPLOY: 'false'" in worker
    assert "FREE_ONLY_EXECUTION_APPROVED: 'false'" in worker


def test_preflight_has_no_write_permissions_or_external_side_effects():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    preflight = workflow.split("  safety-preflight:", 1)[1].split("\n  minimal-loop:", 1)[0]
    assert "permissions:\n      actions: read\n      contents: read" in preflight
    assert "git push" not in preflight
    assert "gh issue create" not in preflight
    assert "curl " not in preflight
    assert "secrets.ORCA_APPROVAL_JSON" not in preflight
    assert "secrets.ORCA_BUDGET_EVIDENCE_JSON" not in preflight


def test_postrun_preserves_blocked_source_report_semantics():
    workflow = (ROOT / ".github" / "workflows" / "distributed-loop-postrun.yml").read_text(encoding="utf-8")
    assert 'source_blocked = "- 結果: **BLOCKED**" in original_report' in workflow
    assert 'catalog_blocked = source_blocked and result_reason.startswith((' in workflow
    assert '"catalog_exhausted_held:"' in workflow
    assert '"catalog_exhausted_review_pending:"' in workflow
    assert '"catalog_exhausted_mixed:"' in workflow
    assert "Source workflow final report is BLOCKED" in workflow


def test_legacy_publication_and_queue_mutations_are_confined_to_inert_worker():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    worker = workflow.split("\n  minimal-loop:", 1)[1]
    assert "Publish verified development branch" in worker
    assert "Publish cloud Orca runtime snapshot" in worker
    assert "git push" in worker
    assert "gh issue create" in worker
    assert "issues: write" not in workflow
    assert "contents: write" not in workflow
    assert "needs.safety-preflight.outputs.execution_enabled == 'true' && false" in worker


def test_schedule_side_effects_remain_suppressed():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "if: always() && github.event_name != 'schedule'" in workflow
    assert "FREE_ONLY_EXECUTION_APPROVED: 'false'" in workflow
