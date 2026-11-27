"""Contract tests for the 30-minute Distributed Loop schedule."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_dedicated_scheduler_dispatches_every_30_minutes():
    scheduler = ROOT / ".github" / "workflows" / "distributed-loop-30m-scheduler.yml"
    text = scheduler.read_text(encoding="utf-8")
    event_block = text.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "schedule:" in event_block
    assert 'cron: "13,43 * * * *"' in event_block
    assert "workflow_dispatch:" in event_block
    assert "gh workflow run distributed-autonomous-loop.yml" in text
    assert "-f max_tasks=1" in text
    assert "Write machine-readable scheduler decision" in text
    assert "scheduler-decision-${{ github.run_id }}" in text
    assert "retention-days: 14" in text
    assert "execution_approval" in text
    assert "DISPATCH_UNCONFIRMED" in text


def test_distributed_loop_is_not_a_second_scheduled_entrypoint():
    text = WORKFLOW.read_text(encoding="utf-8")
    event_block = text.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "schedule:" not in event_block
    assert "workflow_dispatch:" in event_block


def test_scheduled_loop_is_bounded_to_one_task_and_serialized():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event_name == 'schedule' && '1'" in text
    assert "group: distributed-autonomous-loop" in text
    assert "cancel-in-progress: false" in text
    assert "AUTO_APPLY_PATCH: 'false'" in text
    assert "AUTO_DEPLOY: 'false'" in text


def test_recovery_ai_durable_write_refreshes_freshness_timestamp():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "recovery['state_updated_at'] = datetime.now(timezone.utc).isoformat()" in text
    assert "data['recovery_ai'] = recovery" in text



def test_recovery_ai_readback_ignores_only_freshness_timestamp_and_validates_it():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "durable_compare.pop('state_updated_at', None)" in text
    assert "expected_compare.pop('state_updated_at', None)" in text
    assert "datetime.fromisoformat(timestamp.replace('Z', '+00:00'))" in text
    assert "if durable_compare != expected_compare:" in text
    assert "Recovery AI durable read-back mismatch" in text
