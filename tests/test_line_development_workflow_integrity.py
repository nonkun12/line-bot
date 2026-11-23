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
    assert "E2E test-only instruction detected" in text
    assert 'echo "test_only=true" >> "$GITHUB_OUTPUT"' in text
    assert 'python -m pytest -q --tb=native' in text
    assert 'steps.development.outputs.test_only != \'true\'' in text


def test_dispatch_workflow_verifies_task_approval_before_any_execution_path():
    workflow_path = ROOT / ".github" / "workflows" / _WORKFLOW_FILE
    text = workflow_path.read_text(encoding="utf-8")
    approval_marker = "- name: Verify task-bound approval before any execution path"
    runtime_marker = "- name: Run bounded multi-agent LINE development runtime"
    scaffold_marker = "python -m scripts.create_app_scaffold"
    assert approval_marker in text
    assert text.index(approval_marker) < text.index(runtime_marker)
    assert text.index(approval_marker) < text.index(scaffold_marker)
    approval_step = text[
        text.index(approval_marker) : text.index(runtime_marker)
    ]
    assert "from scripts.run_guarded_runtime import _verify_execution_approval" in approval_step
    assert 'evidence.get("gate") != "PASS"' in approval_step
    assert 'evidence.get("execution_authorized") is not True' in approval_step
    assert "checked_out_head != approved_base" in approval_step


def test_dispatch_workflow_propagates_one_stable_cross_interface_task_id():
    workflow_path = ROOT / ".github" / "workflows" / _WORKFLOW_FILE
    text = workflow_path.read_text(encoding="utf-8")
    assert "task_id:" in text
    assert "required: false" in text
    assert "id: prepare_task" in text
    assert "task_id = os.environ.get(\"DEV_TASK_ID\", \"\").strip()" in text
    assert '"AUTONOMOUS_TASK_ID": task_id' in text
    assert "steps.prepare_task.outputs.task_id" in text
    assert "line-development-task-${{ steps.prepare_task.outputs.task_id || github.run_id }}" in text
    assert "Task ID: \\`${DEV_TASK_ID}\\`" in text


def test_dispatch_workflow_names_runs_with_the_shared_task_id():
    workflow_path = ROOT / ".github" / "workflows" / _WORKFLOW_FILE
    text = workflow_path.read_text(encoding="utf-8")
    assert "run-name: LINE task ${{ inputs.task_id || github.run_id }}" in text
