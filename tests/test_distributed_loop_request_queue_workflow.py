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



def test_line_can_resume_any_held_task_only_with_two_explicit_confirmations():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "distributed-autonomous-loop.yml"
    ).read_text(encoding="utf-8")

    assert "startsWith(github.event.comment.body, '/distributed-loop resume_task_id=')" in workflow
    assert "confirm_cause_fixed=true reviewed=true" in workflow
    assert "confirm_resume_review:" in workflow
    assert "CONFIRM_RESUME_REVIEW_INPUT" in workflow
    assert "steps.validate_resume_request.outputs.task_id" in workflow
    assert "python -m scripts.confirm_recovery_resume_review" in workflow
    assert "--recovery-state-file /tmp/recovery-ai-state.json" in workflow


def test_held_task_resume_stays_bounded_to_one_task():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "distributed-autonomous-loop.yml"
    ).read_text(encoding="utf-8")

    assert "startsWith(github.event.comment.body, '/distributed-loop resume_task_id=') && '1'" in workflow
    assert "resume_task_id=([A-Za-z0-9._-]{1,100})" in workflow
