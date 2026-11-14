from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_distributed_loop_uses_free_only_provider_free_task_execution():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "AUTONOMOUS_FREE_MODE: 'true'" in text
    assert "secrets.GROQ_API_KEY" not in text
    assert "GROQ_API_KEY:" not in text
    assert "HERMES_ADVISOR_ENABLED: 'false'" in text
    assert "AUTO_APPLY_PATCH: 'false'" in text
    assert "AUTO_DEPLOY: 'false'" in text


def test_distributed_loop_filters_queue_before_launching_any_task():
    text = WORKFLOW.read_text(encoding="utf-8")
    filter_position = text.index("scripts.free_only_task_queue")
    run_position = text.index("- name: Run one bounded autonomous task")
    assert filter_position < run_position
    assert "AUTONOMOUS_LOOP_TASK_QUEUE=/tmp/autonomous-loop-free-queue.json" in text
    assert "free_only_no_deterministic_tasks" in text


def test_distributed_loop_keeps_no_deterministic_work_fail_closed():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "eligible_deterministic_count" in text
    assert "model-backed tasks are excluded in free-only mode" in text
    assert "BLOCKED:" in text
