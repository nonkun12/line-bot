from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "prepare-autonomous-execution-approval.yml"


def test_approval_preflight_is_manual_read_only_and_artifact_backed():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "required: true" in source
    assert "permissions:\n  contents: read" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "github.actor == github.repository_owner" in source
    assert "autonomous-loop-state" in source
    assert "scripts.autonomous_task_refill" in source
    assert "scripts.prepare_autonomous_execution_approval" in source
    assert "execution_authorized" not in source
    assert "contents: write" not in source
    assert "issues: write" not in source
    assert "pull-requests: write" not in source
    assert "actions: write" not in source
    assert "gh pr create" not in source
    assert "git push" not in source
    assert "actions/upload-artifact@v4" in source


def test_manifest_clearly_requires_human_dispatch_and_does_not_execute():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "This workflow is read-only" in source
    assert "does not approve, queue, execute, merge, or deploy anything" in source
    assert "APPROVE_EXECUTION" in source
    assert "approval_base_sha" not in source  # summary labels show the field values for manual dispatch
