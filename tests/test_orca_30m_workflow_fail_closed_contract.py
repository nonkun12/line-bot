"""Fail-closed contract tests for the unified 30-minute LOOP workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_preflight_is_read_only_and_execution_is_permanently_disabled():
    source = WORKFLOW.read_text(encoding="utf-8")
    preflight = source.split("  safety-preflight:", 1)[1].split("\n  minimal-loop:", 1)[0]
    worker = source.split("\n  minimal-loop:", 1)[1]

    assert "permissions:\n      actions: read\n      contents: read" in preflight
    assert "needs: safety-preflight" in worker
    assert "needs.safety-preflight.outputs.execution_enabled == 'true' && false" in worker
    assert "permissions:\n      actions: read\n      contents: read" in worker
    assert "MAX_TASKS: '1'" in worker
    assert "AUTO_APPLY_PATCH: 'false'" in worker
    assert "AUTO_DEPLOY: 'false'" in worker
    assert "FREE_ONLY_EXECUTION_APPROVED: 'false'" in worker


def test_preflight_code_never_enables_execution_until_worker_is_integrated():
    source = (ROOT / "scripts" / "orca_30m_preflight.py").read_text(encoding="utf-8")
    assert '"status": "BLOCKED"' in source
    assert '"reason": "phase3_worker_runtime_not_integrated"' in source
    assert '"execution_enabled": False' in source
    assert 'handle.write("execution_enabled=false\\n")' in source


def test_typed_worker_contracts_remain_validation_only():
    registry = (ROOT / "scripts" / "orca_github_task_registry.py").read_text(encoding="utf-8")
    worker = (ROOT / "scripts" / "orca_github_worker_dry_run.py").read_text(encoding="utf-8")
    assert '"execution_supported": False' in registry
    assert '"status": "BLOCKED_HANDLER_NOT_IMPLEMENTED"' in registry
    assert '"execution_started": False' in worker
    assert '"execution_supported": False' in worker


def test_unified_loop_job_has_no_legacy_runtime_or_external_side_effects():
    source = WORKFLOW.read_text(encoding="utf-8")
    worker = source.split("\n  minimal-loop:", 1)[1]
    forbidden = (
        "run_minimal_autonomous_loop.py",
        "autonomous_task_refill",
        "autonomous_task_proposals",
        "gh issue create",
        "git push",
        "INTERNAL_PUSH_KEY",
        "ORCA_STATUS_SECRET",
        "agents.sheets",
        "curl ",
        "upload-artifact",
    )
    assert not any(token in worker for token in forbidden)


def test_workflow_has_no_write_permissions_and_no_external_notification_steps():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  actions: read\n  contents: read" in source
    assert "actions: write" not in source
    assert "contents: write" not in source
    assert "issues: write" not in source
    assert "pull-requests: write" not in source
    assert "Notify LINE" not in source
    assert "Publish cloud Orca runtime snapshot" not in source
