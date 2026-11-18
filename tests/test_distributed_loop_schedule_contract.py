"""Contract tests for the 30-minute Distributed Loop schedule."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_distributed_loop_runs_every_30_minutes():
    text = WORKFLOW.read_text(encoding="utf-8")
    event_block = text.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "schedule:" in event_block
    assert 'cron: "17,47 * * * *"' in event_block


def test_scheduled_loop_is_bounded_to_one_task_and_serialized():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event_name == 'schedule' && '1'" in text
    assert "group: distributed-autonomous-loop" in text
    assert "cancel-in-progress: false" in text
    assert "AUTO_APPLY_PATCH: 'false'" in text
    assert "AUTO_DEPLOY: 'false'" in text

def test_only_main_loop_owns_the_automatic_30_minute_schedule():
    scheduler = ROOT / ".github" / "workflows" / "distributed-loop-30m-scheduler.yml"
    text = scheduler.read_text(encoding="utf-8")
    event_block = text.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in event_block
    assert "schedule:" not in event_block
