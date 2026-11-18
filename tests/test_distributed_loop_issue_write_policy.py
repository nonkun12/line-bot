"""Safety contract for automatic GitHub Issue writes in the distributed loop."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOOP = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"
POSTRUN = ROOT / ".github" / "workflows" / "distributed-loop-postrun.yml"


def test_review_issue_creation_is_explicitly_opt_in_for_manual_runs():
    source = LOOP.read_text(encoding="utf-8")
    input_block = source.split("      allow_review_issue_creation:", 1)[1].split("      ", 1)[0]
    assert "default: false" in input_block
    assert "type: boolean" in input_block
    step = source.split(
        "      - name: Create bounded review-only task issues from analyzer findings", 1
    )[1].split("      - name: Run one bounded autonomous task", 1)[0]
    assert "github.event_name == 'workflow_dispatch'" in step
    assert "inputs.allow_review_issue_creation == true" in step


def test_postrun_verification_preserves_findings_without_issue_write_permission():
    source = POSTRUN.read_text(encoding="utf-8")
    permissions = source.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "issues: write" not in permissions
    assert "gh issue create" not in source
    assert "actions/upload-artifact@v4" in source
    assert "postrun-findings.json" in source
    assert "postrun-report.md" in source
