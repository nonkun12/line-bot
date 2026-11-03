"""Regression coverage for deterministic refill test append ordering."""
from pathlib import Path

import pytest

from core import line_development_runtime as runtime


EOF_ANCHOR = '    assert queue.read_text(encoding="utf-8") == queue_before'
FIRST_TASK_END = '    assert [task["id"] for task in runtime_queue["tasks"]] == ["task-cli-new"]'
FIRST_TASK = "task-refill-cli-test-20261102"
SECOND_TASK = "task-refill-read-json-test-20261102"
TARGET = "tests/test_autonomous_task_refill.py"


def _apply(task_id: str, root: Path) -> None:
    plan, error = runtime._deterministic_autonomous_test_plan(TARGET, task_id)
    assert error is None
    assert plan is not None
    change = plan["changes"][0]
    path = root / change["file"]
    content = path.read_text(encoding="utf-8")
    assert content.count(change["old"]) == 1
    path.write_text(content.replace(change["old"], change["new"], 1), encoding="utf-8")


@pytest.mark.parametrize("order", [
    (FIRST_TASK, SECOND_TASK),
    (SECOND_TASK, FIRST_TASK),
])
def test_two_refill_tasks_append_in_stable_file_order(tmp_path, monkeypatch, order):
    target = tmp_path / TARGET
    target.parent.mkdir(parents=True)
    target.write_text(
        "from pathlib import Path\n\n"
        "def test_existing_refill_case():\n"
        "    queue = Path('queue.json')\n"
        f"{EOF_ANCHOR}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    for task_id in order:
        _apply(task_id, tmp_path)

    content = target.read_text(encoding="utf-8")
    assert content.count("def test_refill_main_cli_adds_one_approved_task(") == 1
    assert content.count("def test_read_json_rejects_non_object_root(") == 1
    assert content.index("def test_refill_main_cli_adds_one_approved_task(") < content.index(
        "def test_read_json_rejects_non_object_root("
    )
    assert content.rstrip().endswith("read_json(path)")



def test_two_refill_task_orders_produce_identical_file_bytes(tmp_path, monkeypatch):
    roots = [tmp_path / "cli-first", tmp_path / "read-json-first"]
    for root in roots:
        target = root / TARGET
        target.parent.mkdir(parents=True)
        target.write_text(
            "from pathlib import Path\\n\\n"
            "def test_existing_refill_case():\\n"
            "    queue = Path('queue.json')\\n"
            f"{EOF_ANCHOR}\\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(runtime.worker, "ROOT", roots[0])
    for task_id in (FIRST_TASK, SECOND_TASK):
        _apply(task_id, roots[0])

    monkeypatch.setattr(runtime.worker, "ROOT", roots[1])
    for task_id in (SECOND_TASK, FIRST_TASK):
        _apply(task_id, roots[1])

    first = (roots[0] / TARGET).read_bytes()
    second = (roots[1] / TARGET).read_bytes()
    assert first == second
