from pathlib import Path

def test_review_issue_publisher_is_separate_and_scoped():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert "publish-review-issues:" in workflow
    assert "needs: minimal-loop" in workflow
    assert "issues: write" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "scripts.publish_autonomous_task_issue_drafts" in workflow
