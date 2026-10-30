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

