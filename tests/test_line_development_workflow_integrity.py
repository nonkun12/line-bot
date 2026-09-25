from pathlib import Path

from line_development import _WORKFLOW_FILE


ROOT = Path(__file__).resolve().parents[1]


def test_dispatch_target_is_a_real_manual_workflow():
    workflow_path = ROOT / ".github" / "workflows" / _WORKFLOW_FILE
    assert workflow_path.is_file()
    text = workflow_path.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text


def test_dispatch_workflow_keeps_e2e_test_only_gate():
    workflow_path = ROOT / ".github" / "workflows" / _WORKFLOW_FILE
    text = workflow_path.read_text(encoding="utf-8")
    assert "Explicit test-only instruction detected" in text
    assert 'echo "test_only=true" >> "$GITHUB_OUTPUT"' in text
    assert 'python -m pytest -q --tb=native' in text
    assert 'steps.development.outputs.test_only != \'true\'' in text
