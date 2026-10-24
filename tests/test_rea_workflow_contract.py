from pathlib import Path


def test_rea_audit_workflow_emits_review_only_control_tower_evidence():
    workflow = Path(".github/workflows/rea-readonly-audit.yml").read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "python -m scripts.rea_readonly_scanner --repo-root ." in workflow
    assert "python -m scripts.rea_review_candidates rea-report.json --expected-sha" in workflow
    assert "ControlTower.evaluate_rea_review_candidates(candidates, expected_sha=expected_sha)" in workflow
    assert "rea-control-tower-decision.json" in workflow
    assert "task_template_id" in workflow
    assert "No code was changed" in workflow
