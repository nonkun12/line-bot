import json
from pathlib import Path


def test_new_replenishment_tasks_are_explicitly_approved_and_test_scoped():
    catalog = json.loads((Path(__file__).resolve().parents[1] / ".github" / "autonomous-loop-task-catalog.json").read_text(encoding="utf-8"))
    by_id = {task["id"]: task for task in catalog["tasks"]}
    expected = {
        "recovery-resume-review-cli-test-20261102": "tests/test_confirm_recovery_resume_review.py",
        "catalog-exhaustion-analyzer-cli-test-20261102": "tests/test_catalog_exhaustion_analyzer.py",
        "task-refill-cli-test-20261102": "tests/test_autonomous_task_refill.py",
        "task-refill-read-json-test-20261102": "tests/test_autonomous_task_refill.py",
    }
    for task_id, path in expected.items():
        task = by_id[task_id]
        assert task["execution_approved"] is True
        assert task["allowed_paths"] == [path]
        assert "Append the new test at the end" in task["instruction"]
        assert "Do not edit" in task["instruction"]


def test_seeded_cli_tasks_include_exact_runtime_contract_expectations():
    catalog = json.loads((Path(__file__).resolve().parents[1] / ".github" / "autonomous-loop-task-catalog.json").read_text(encoding="utf-8"))
    tasks = {task["id"]: task for task in catalog["tasks"]}
    assert "called['state_path'] == str(state_file)" in tasks["recovery-resume-review-cli-test-20261102"]["instruction"]
    assert 'candidate_count is 1' in tasks["catalog-exhaustion-analyzer-cli-test-20261102"]["instruction"]
    assert "added_ids == ['task-cli-new']" in tasks["task-refill-cli-test-20261102"]["instruction"]
    assert "JSON root must be an object" in tasks["task-refill-read-json-test-20261102"]["instruction"]
    for task_id in (
        "recovery-resume-review-cli-test-20261102",
        "catalog-exhaustion-analyzer-cli-test-20261102",
        "task-refill-cli-test-20261102",
        "task-refill-read-json-test-20261102",
    ):
        assert tasks[task_id]["execution_approved"] is True
        assert "Append the new test at the end" in tasks[task_id]["instruction"]
