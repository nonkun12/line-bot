"""Contract tests for read-only scheduled observation and guarded execution."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBSERVATION = ROOT / ".github" / "workflows" / "distributed-autonomous-observation.yml"
EXECUTION = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_observation_runs_every_30_minutes():
    text = OBSERVATION.read_text(encoding="utf-8")
    event_block = text.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "schedule:" in event_block
    assert 'cron: "0,30 * * * *"' in event_block


def test_scheduled_observation_is_read_only_and_execution_is_manual():
    observation = OBSERVATION.read_text(encoding="utf-8")
    execution = EXECUTION.read_text(encoding="utf-8")
    event_block = execution.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "schedule:" not in event_block
    assert "workflow_dispatch:" in event_block
    assert "execution_approval:" in event_block
    assert "default: 'DENY'" in event_block
    assert "contents: read" in observation.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "issues: read" in observation.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "pull-requests: read" in observation.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "write" not in observation.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "AUTO_APPLY_PATCH: 'false'" in execution
    assert "AUTO_DEPLOY: 'false'" in execution


def test_execution_preserves_non_cancelling_concurrency_queue():
    text = EXECUTION.read_text(encoding="utf-8")
    concurrency = text.split("concurrency:", 1)[1].split("jobs:", 1)[0]
    assert "group: distributed-autonomous-loop" in concurrency
    assert "cancel-in-progress: false" in concurrency
    assert "queue: max" in concurrency


def test_recovery_ai_durable_write_refreshes_freshness_timestamp():
    text = EXECUTION.read_text(encoding="utf-8")
    assert "recovery['state_updated_at'] = datetime.now(timezone.utc).isoformat()" in text
    assert "data['recovery_ai'] = recovery" in text



def test_recovery_ai_readback_ignores_only_freshness_timestamp_and_validates_it():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "durable_compare.pop('state_updated_at', None)" in text
    assert "expected_compare.pop('state_updated_at', None)" in text
    assert "datetime.fromisoformat(timestamp.replace('Z', '+00:00'))" in text
    assert "if durable_compare != expected_compare:" in text
    assert "Recovery AI durable read-back mismatch" in text
