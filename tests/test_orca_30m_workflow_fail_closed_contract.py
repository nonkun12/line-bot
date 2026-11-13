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


def test_scheduled_runs_do_not_wake_render_or_consume_line_push_quota():
    source = WORKFLOW.read_text(encoding="utf-8")
    for step_name in (
        "Wake Render before LINE final report",
        "Notify LINE of distributed loop final report",
    ):
        lines = source.splitlines()
        step_index = lines.index(f"      - name: {step_name}")
        assert lines[step_index + 1].strip() == "if: always() && github.event_name != 'schedule'"

def test_workflow_and_legacy_loop_job_have_no_write_permissions():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  actions: read\n  contents: read" in source
    worker = source.split("\n  minimal-loop:", 1)[1]
    header = worker.split("\n    steps:", 1)[0]
    assert "permissions:\n      actions: read\n      contents: read" in header
    assert "actions: write" not in source
    assert "contents: write" not in source
    assert "issues: write" not in source
    assert "pull-requests: write" not in source


def test_unified_loop_job_is_inert_and_contains_no_legacy_or_external_side_effects():
    source = WORKFLOW.read_text(encoding="utf-8")
    worker = source.split("\\n  minimal-loop:", 1)[1]

    assert "needs: safety-preflight" in worker
    assert "needs.safety-preflight.outputs.execution_enabled == 'true' && false" in worker
    assert "permissions:\\n      actions: read\\n      contents: read" in worker
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
    )
    assert not any(token in worker for token in forbidden)
