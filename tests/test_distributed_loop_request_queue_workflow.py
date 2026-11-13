from __future__ import annotations

from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "distributed-autonomous-loop.yml"
)


def test_distributed_loop_keeps_native_pending_run_queue():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    concurrency = workflow.split("concurrency:", 1)[1].split("\njobs:", 1)[0]
    assert "group: distributed-autonomous-loop" in concurrency
    assert "cancel-in-progress: false" in concurrency
    assert "queue: max" in concurrency


def test_request_and_resume_inputs_are_retained_but_worker_stays_inert():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "request_id:" in workflow
    assert "resume_task_id:" in workflow
    assert "confirm_cause_fixed:" in workflow
    assert "confirm_resume_review:" in workflow
    worker = workflow.split("\n  minimal-loop:", 1)[1]
    assert "needs.safety-preflight.outputs.execution_enabled == 'true' && false" in worker


def test_queue_safety_defaults_remain_explicitly_disabled():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "AUTO_APPLY_PATCH: 'false'" in workflow
    assert "AUTO_DEPLOY: 'false'" in workflow
    assert "HERMES_ADVISOR_ENABLED: 'false'" in workflow
    assert "SELF_IMPROVEMENT_CREATOR_CRITIC: 'false'" in workflow
    assert "FREE_ONLY_EXECUTION_APPROVED: 'false'" in workflow


def test_actionlint_compatibility_ignore_is_scoped_to_this_workflow():
    config = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "actionlint.yaml"
    ).read_text(encoding="utf-8")
    assert '".github/workflows/distributed-autonomous-loop.yml":' in config
    assert 'unexpected key "queue" for "concurrency" section' in config
    assert "ignore:" in config


def test_resume_request_cannot_bypass_inert_candidate_worker():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    worker = workflow.split("\n  minimal-loop:", 1)[1]
    assert "python -m scripts.confirm_recovery_resume_review" not in worker
    assert "needs.safety-preflight.outputs.execution_enabled == 'true' && false" in worker
