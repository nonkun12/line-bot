from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-observation.yml"


def test_scheduled_observation_runs_work_finder_with_durable_read_only_inputs():
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "0,30 * * * *"' in source
    assert "Set up Python for Work Finder AI" in source
    assert "python -m scripts.work_finder_ai" in source
    assert "--catalog .github/autonomous-loop-task-catalog.json" in source
    assert "--queue .github/autonomous-loop-tasks.json" in source
    assert "--state /tmp/autonomous-loop-state.json" in source
    assert "--runtime core/line_development_runtime.py" in source
    assert "--existing-issues /tmp/autonomous-loop-all-issues.json" in source
    assert "--output /tmp/work-finder-report.json" in source


def test_observation_restores_and_validates_durable_state_without_git_write_credentials():
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "persist-credentials: false" in source
    assert "contents: read" in source
    assert "contents/.autonomous-loop-state.json?ref=autonomous-loop-state" in source
    assert 'base64.b64decode("".join(encoded.split()), validate=True)' in source
    assert 'recovery.get("schema_version") != 1' in source
    assert '"/tmp/autonomous-loop-state.json"' in source
    assert '"/tmp/autonomous-loop-all-issues.json"' in source


def test_work_finder_evidence_is_in_summary_and_uploaded_artifact():
    source = WORKFLOW.read_text(encoding="utf-8")

    assert '"/tmp/work-finder-report.json"' in source
    assert '"/tmp/distributed-observation.json"' in source
    assert "cat /tmp/work-finder-report.json >> \"$GITHUB_STEP_SUMMARY\"" in source
    assert "Upload observation and Work Finder evidence" in source
    assert "retention-days: 30" in source


def test_observation_cannot_approve_or_execute_tasks_or_write_github_state():
    source = WORKFLOW.read_text(encoding="utf-8")
    permissions = source.split("permissions:", 1)[1].split("concurrency:", 1)[0]

    assert "actions: read" in permissions
    assert "contents: read" in permissions
    assert "issues: read" in permissions
    assert "pull-requests: read" in permissions
    assert "actions: write" not in permissions
    assert "contents: write" not in permissions
    assert "issues: write" not in permissions
    assert "pull-requests: write" not in permissions
    assert "gh issue create" not in source
    assert "gh workflow run" not in source
    assert "execution_approval" not in source
    assert "run_guarded_runtime" not in source
    assert "AUTO_APPLY_PATCH" not in source
    assert "AUTO_DEPLOY" not in source
