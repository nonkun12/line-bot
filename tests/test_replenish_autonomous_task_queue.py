from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.replenish_autonomous_task_queue import build_queue


def test_rebuild_fills_queue_from_only_allowlisted_deterministic_targets():
    existing = {
        "version": 1,
        "max_tasks_per_run": 4,
        "tasks": [{
            "id": "known-task",
            "instruction": "Reviewed instruction",
            "allowed_paths": ["tests/test_known.py"],
        }],
    }
    targets = {
        "known-task": "tests/test_known.py",
        "new-known-task": "uhip/tests/test_contract.py",
    }

    rebuilt = build_queue(existing, targets)

    assert rebuilt["max_tasks_per_run"] == 4
    assert [task["id"] for task in rebuilt["tasks"]] == ["known-task", "new-known-task"]
    assert rebuilt["tasks"][0]["instruction"] == "Reviewed instruction"
    assert rebuilt["tasks"][1]["allowed_paths"] == ["uhip/tests/test_contract.py"]
    assert all(len(task["allowed_paths"]) == 1 for task in rebuilt["tasks"])


@pytest.mark.parametrize("target", [
    "../secrets.env",
    "/tmp/unsafe.py",
    "scripts/deploy.py",
    "tests/../../secrets.env",
])
def test_rebuild_rejects_paths_outside_test_allowlist(target):
    with pytest.raises(ValueError):
        build_queue({"tasks": []}, {"unsafe-task": target})


def test_rebuild_rejects_duplicate_existing_ids():
    existing = {"tasks": [
        {"id": "same", "instruction": "one", "allowed_paths": ["tests/test_one.py"]},
        {"id": "same", "instruction": "two", "allowed_paths": ["tests/test_two.py"]},
    ]}
    with pytest.raises(ValueError, match="duplicate"):
        build_queue(existing, {"same": "tests/test_one.py"})


def test_rebuild_fails_closed_on_empty_catalog():
    with pytest.raises(ValueError, match="empty"):
        build_queue({"tasks": []}, {})
