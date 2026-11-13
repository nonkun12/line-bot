"""Fail-closed contract tests for the unified 30-minute LOOP workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_execution_job_requires_explicit_success_from_read_only_preflight():
    source = WORKFLOW.read_text(encoding="utf-8")
    preflight = source.split("  safety-preflight:", 1)[1].split("\n  minimal-loop:", 1)[0]
    worker = source.split("\n  minimal-loop:", 1)[1]

    assert "permissions:\n      actions: read\n      contents: read" in preflight
    assert "needs: safety-preflight" in worker
    assert "needs.safety-preflight.outputs.execution_enabled == 'true'" in worker
    assert "FREE_ONLY_EXECUTION_APPROVED: 'false'" in worker
    assert "AUTO_APPLY_PATCH: 'false'" in worker
    assert "AUTO_DEPLOY: 'false'" in worker


def test_preflight_is_a_permanent_non_execution_gate_until_worker_is_implemented():
    source = (ROOT / "scripts" / "orca_30m_preflight.py").read_text(encoding="utf-8")
    assert '"status": "BLOCKED"' in source
    assert '"reason": "phase3_worker_runtime_not_integrated"' in source
    assert '"execution_enabled": False' in source
    assert 'handle.write("execution_enabled=false\\n")' in source


def test_typed_worker_contracts_cannot_be_mistaken_for_executable_handlers():
    registry = (ROOT / "scripts" / "orca_github_task_registry.py").read_text(encoding="utf-8")
    worker = (ROOT / "scripts" / "orca_github_worker_dry_run.py").read_text(encoding="utf-8")
    assert '"execution_supported": False' in registry
    assert '"status": "BLOCKED_HANDLER_NOT_IMPLEMENTED"' in registry
    assert '"execution_started": False' in worker
    assert '"execution_supported": False' in worker
