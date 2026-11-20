from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXECUTION = ROOT / ".github/workflows/distributed-autonomous-loop.yml"
OBSERVATION = ROOT / ".github/workflows/distributed-autonomous-observation.yml"


def test_distributed_execution_is_manual_and_explicitly_approved():
    workflow = EXECUTION.read_text(encoding="utf-8")
    trigger_block = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "workflow_dispatch:" in trigger_block
    assert "schedule:" not in trigger_block
    assert "issue_comment:" not in trigger_block
    assert "pull_request_target:" not in trigger_block
    assert "github.event.inputs.execution_approval == 'APPROVE_EXECUTION'" in workflow
    assert "github.event.inputs.mode == 'normal'" in workflow
    assert "actions: read" in workflow.split("jobs:", 1)[0]
    assert "contents: read" in workflow.split("jobs:", 1)[0]
    assert "issues: read" in workflow.split("jobs:", 1)[0]
    job_permissions = workflow.split("jobs:", 1)[1].split("runs-on:", 1)[0]
    assert "pull-requests: read" in job_permissions
    assert "pull-requests: write" not in job_permissions


def test_execution_approval_gate_precedes_task_runtime_and_mutating_steps():
    workflow = EXECUTION.read_text(encoding="utf-8")
    gate = workflow.index("Verify one-shot task-bound execution approval")
    runtime = workflow.index("Run one bounded autonomous task")
    refill = workflow.index("Prepare bounded runtime task refill")
    issue_read = workflow.index("Load all existing issues for candidate deduplication")
    assert refill < gate < issue_read < runtime
    assert "python -m scripts.distributed_loop_execution_approval" in workflow
    approval_step = workflow.split("Verify one-shot task-bound execution approval", 1)[1].split("      - name:", 1)[0]
    assert "--catalog .github/autonomous-loop-task-catalog.json" in approval_step
    assert "gh issue create" not in workflow
    assert "work_finder_ai" not in workflow
    assert "AUTO_APPLY_PATCH: 'false'" in workflow
    assert "AUTO_DEPLOY: 'false'" in workflow


def test_observation_workflow_is_scheduled_read_only_and_artifact_only():
    workflow = OBSERVATION.read_text(encoding="utf-8")
    trigger_block = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    permissions = workflow.split("permissions:", 1)[1].split("\nconcurrency:", 1)[0]
    assert 'cron: "0,30 * * * *"' in trigger_block
    for permission in ("actions: read", "contents: read", "issues: read", "pull-requests: read"):
        assert permission in permissions
    assert "write" not in permissions
    lowered = workflow.lower()
    for forbidden in ("gh issue create", "gh pr create", "git push", "update_file", "delete_file"):
        assert forbidden not in lowered
    assert "actions/upload-artifact" in workflow
    assert "READ_ONLY" in workflow



def test_resume_is_blocked_until_its_own_approval_binding_exists():
    workflow = EXECUTION.read_text(encoding="utf-8")
    assert "Block held-task resume until task-bound resume approval is implemented" in workflow
    assert "Resume one explicitly approved held task" not in workflow


def test_observation_flattens_paginated_workflow_run_envelopes_without_exposing_instructions():
    workflow = OBSERVATION.read_text(encoding="utf-8")
    assert 'pages("/tmp/runs-pages.json", "workflow_runs")' in workflow
    assert '"instruction": x.get("instruction")' not in workflow


def test_observation_instruction_digest_uses_approval_normalization():
    workflow = OBSERVATION.read_text(encoding="utf-8")
    assert 'str(x.get("instruction", "")).strip()[:2000]' in workflow
    assert 'hashlib.sha256(str(x.get("instruction", "")).encode("utf-8"))' not in workflow


def test_legacy_autonomous_worker_is_disabled_until_task_bound_approval_exists():
    workflow = (ROOT / ".github/workflows/nightly-autonomous-worker.yml").read_text(encoding="utf-8")
    trigger_block = workflow.split("\non:\n", 1)[1].split("\n# Legacy worker", 1)[0]
    assert "workflow_dispatch:" in trigger_block
    assert "schedule:" not in trigger_block
    assert "github.event_name == 'workflow_dispatch' && false" in workflow
    assert "execution_approval" not in workflow
    assert "approval_task_id" not in workflow
    assert "approval_instruction_sha256" not in workflow
    assert "approval_allowed_paths_sha256" not in workflow
    assert "approval_base_sha" not in workflow
    top_permissions = workflow.split("permissions:", 1)[1].split("\nconcurrency:", 1)[0]
    assert "contents: read" in top_permissions
    assert "pull-requests: read" in top_permissions
    assert "contents: write" not in workflow
    assert "pull-requests: write" not in workflow
