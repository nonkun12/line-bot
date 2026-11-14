"""Fail-closed contract tests for the unified 30-minute LOOP workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_preflight_and_worker_have_read_only_permissions_and_hard_stop():
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


def test_legacy_runtime_is_present_only_behind_the_permanent_false_job_gate():
    source = WORKFLOW.read_text(encoding="utf-8")
    worker = source.split("\n  minimal-loop:", 1)[1]
    assert "needs.safety-preflight.outputs.execution_enabled == 'true' && false" in worker
    assert "python scripts/run_minimal_autonomous_loop.py" in worker
    assert "autonomous_task_refill" in worker
    assert "Publish verified development branch" in worker


def test_workflow_has_no_write_permissions_or_secrets_in_blocked_preflight():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  actions: read\n  contents: read" in source
    assert "actions: write" not in source
    assert "contents: write" not in source
    assert "issues: write" not in source
    assert "pull-requests: write" not in source
    preflight = source.split("  safety-preflight:", 1)[1].split("\n  minimal-loop:", 1)[0]
    for secret in (
        "secrets.ORCA_APPROVAL_JSON",
        "secrets.ORCA_APPROVAL_SIGNING_KEY",
        "secrets.ORCA_BUDGET_EVIDENCE_JSON",
        "secrets.ORCA_BUDGET_SIGNING_KEY",
    ):
        assert secret not in preflight


def test_30m_preflight_runs_detailed_read_only_observer_first():
    source = WORKFLOW.read_text(encoding="utf-8")
    preflight = source.split("  safety-preflight:", 1)[1].split("\n  minimal-loop:", 1)[0]

    observer_step = preflight.index("name: Read-only Phase 1 state observation")
    preflight_step = preflight.index("name: Read-only activation preflight")
    assert observer_step < preflight_step
    assert "run: python scripts/orca_github_phase1_observer.py" in preflight
    assert "GITHUB_TOKEN: ${{ github.token }}" in preflight
    assert "ORCA_STATE_BRANCH:" in preflight
    assert "ORCA_STATE_PATH:" in preflight
    assert "permissions:\n      actions: read\n      contents: read" in preflight
    assert "needs.safety-preflight.outputs.execution_enabled == 'true' && false" in source
