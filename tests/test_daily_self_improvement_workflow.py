from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_daily_self_improvement_workflow_is_scheduled_and_review_first():
    path = ROOT / ".github" / "workflows" / "nightly-autonomous-worker.yml"
    text = path.read_text(encoding="utf-8")
    assert "- cron: '0 18 * * *'" in text
    assert "Daily Self-Improvement Loop" in text
    assert "NIGHTLY_AUTOFIX: 'true'" in text
    assert "AUTO_DEPLOY: 'false'" in text
    assert "daily self-improvement" in text
    assert "id: self_improvement" in text
    assert "steps.self_improvement.outcome" in text
    assert "gh pr create" in text
    assert "merge" in text.lower()
    assert "deploy" in text.lower()


def test_daily_verification_disables_autofix():
    path = ROOT / ".github" / "workflows" / "nightly-autonomous-worker.yml"
    text = path.read_text(encoding="utf-8")
    assert "Run read-only final verification" in text
    assert "NIGHTLY_AUTOFIX: 'false'" in text
    assert "id: verification" in text
