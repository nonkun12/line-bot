from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_rea_history_is_restored_appended_exported_and_read_back_separately():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts.rea_self_improvement_history import" in source
    assert "scripts.rea_self_improvement_history append" in source
    assert "scripts.rea_self_improvement_history export" in source
    assert "--history /tmp/line-bot-rea-self-improvement.jsonl" in source
    assert "--results /tmp/minimal-autonomous-loop.jsonl" in source
    assert "--cycle-id "${GITHUB_RUN_ID}"" in source
    assert "data['rea_observations'] = rea_observations" in source
    assert "durable.get('rea_observations', []) != local_state.get('rea_observations', [])" in source


def test_rea_history_does_not_reclassify_blocked_gate_as_task_failure():
    source = WORKFLOW.read_text(encoding="utf-8")
    marker = "# REA gate outcomes are persisted separately; they never train task-failure priority."
    assert marker in source
    assert "append-loop-results" in source
    assert "scripts.rea_self_improvement_history append" in source
