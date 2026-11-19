"""Static regression checks for distributed-loop credential isolation."""
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_task_runtime_does_not_receive_github_token():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index("      - name: Run one bounded autonomous task\n")
    end = workflow.index("      - name: Publish verified development branch\n", start)
    task_step = workflow[start:end]
    assert "GH_TOKEN:" not in task_step
    assert "git remote set-url origin" not in task_step
    assert "x-access-token:" not in task_step


def test_publish_keeps_token_scoped_to_publish_step():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index("      - name: Publish verified development branch\n")
    end = workflow.index("      - name: Persist completed task state\n", start)
    publish_step = workflow[start:end]
    assert "GH_TOKEN: ${{ github.token }}" in publish_step
    assert "auth_url=" in publish_step



def test_isolated_candidate_publisher_never_embeds_token_in_git_remote_url():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index("      - name: Publish isolated REA candidate for independent verification\n")
    end = workflow.index("      - name: Archive isolated candidate evidence\n", start)
    candidate_step = workflow[start:end]
    assert "https://x-access-token:" not in candidate_step
    assert "auth_url" not in candidate_step
    assert "GIT_CONFIG_VALUE_0" in candidate_step
    assert "base64.b64encode" in candidate_step
    assert "GITHUB_TOKEN: ${{ github.token }}" in candidate_step
