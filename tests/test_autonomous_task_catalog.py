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
        assert "既存" not in task["instruction"] or "existing" in task["instruction"].lower()
        assert "existing test" in task["instruction"].lower()
