from __future__ import annotations

from pathlib import Path


def test_distributed_loop_uses_github_native_pending_run_queue():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "distributed-autonomous-loop.yml"
    ).read_text(encoding="utf-8")

    concurrency = workflow.split("concurrency:", 1)[1].split("\njobs:", 1)[0]
    assert "group: distributed-autonomous-loop" in concurrency
    assert "cancel-in-progress: false" in concurrency
    assert "queue: max" in concurrency


def test_line_request_correlation_id_is_optional_and_validated():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "distributed-autonomous-loop.yml"
    ).read_text(encoding="utf-8")

    assert "request_id:" in workflow
    assert "request_id=${{ inputs.request_id || 'scheduled' }}" in workflow
    assert "github.event.inputs.request_id" in workflow
    assert "^[0-9a-f]{32}$" in workflow


def test_queue_does_not_change_safety_limits_or_auto_deploy():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "distributed-autonomous-loop.yml"
    ).read_text(encoding="utf-8")

    assert "AUTO_APPLY_PATCH: 'false'" in workflow
    assert "AUTO_DEPLOY: 'false'" in workflow
    assert "HERMES_ADVISOR_ENABLED: 'false'" in workflow
    assert "SELF_IMPROVEMENT_CREATOR_CRITIC: 'false'" in workflow

def test_actionlint_compatibility_ignore_is_scoped_to_this_workflow():
    config = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "actionlint.yaml"
    ).read_text(encoding="utf-8")

    assert '".github/workflows/distributed-autonomous-loop.yml":' in config
    assert 'unexpected key "queue" for "concurrency" section' in config
    assert "ignore:" in config



def test_held_task_resume_fails_closed_until_task_bound_gate_exists():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "distributed-autonomous-loop.yml"
    ).read_text(encoding="utf-8")
    assert "Block held-task resume until task-bound resume approval is implemented" in workflow
    assert "resume_task_id != ''" in workflow
    assert "exit 1" in workflow
    assert "Resume one explicitly approved held task" not in workflow


def test_held_task_resume_stays_bounded_to_one_manual_approved_task():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "distributed-autonomous-loop.yml"
    ).read_text(encoding="utf-8")
    trigger_block = workflow.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "workflow_dispatch:" in trigger_block
    assert "issue_comment:" not in trigger_block
    assert "max_tasks:" in trigger_block
    assert "execution_approval:" in trigger_block
    assert "default: 'DENY'" in trigger_block
    assert "resume_task_id:" in trigger_block
    assert "confirm_resume_review:" in trigger_block
    assert "Block held-task resume until task-bound resume approval is implemented" in workflow
