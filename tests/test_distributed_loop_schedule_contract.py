"""Contract tests for the 30-minute Distributed Loop schedule."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_distributed_loop_runs_every_30_minutes():
    text = WORKFLOW.read_text(encoding="utf-8")
    event_block = text.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "schedule:" in event_block
    assert 'cron: "0,30 * * * *"' in event_block


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
