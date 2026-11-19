from __future__ import annotations

import json
from pathlib import Path

from scripts.work_finder_ai import find_work


def _write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _fixture(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "core").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "core" / "agent_runtime.py").write_text(
        "def uncovered_boundary(value):\n    return value\n", encoding="utf-8"
    )
    (root / "tests" / "test_agent_runtime.py").write_text(
        "def test_existing():\n    assert True\n", encoding="utf-8"
    )
    catalog = _write(tmp_path / "catalog.json", {"tasks": []})
    queue = _write(tmp_path / "queue.json", {"tasks": []})
    state = _write(tmp_path / "state.json", {
        "completed": [],
        "recovery_ai": {
            "schema_version": 1, "tasks": {}, "checkpoint": None,
        },
    })
    runtime = root / "core" / "line_development_runtime.py"
    runtime.write_text("_DETERMINISTIC_AUTONOMOUS_TASK_TARGETS = {}\n", encoding="utf-8")
    return root, catalog, queue, state, runtime


def test_work_finder_discovers_review_only_work_on_every_cycle(tmp_path: Path):
    root, catalog, queue, state, runtime = _fixture(tmp_path)
    before = [p.read_bytes() for p in (catalog, queue, state, runtime)]

    report = find_work(root, catalog, queue, state, runtime)

    assert report["status"] == "REVIEW_REQUIRED"
    assert report["candidate_count"] == 1
    assert report["work_finder"]["name"] == "Work Finder AI"
    assert report["work_finder"]["cycle_status"] == "WORK_FOUND"
    assert report["work_finder"]["next_action"] == "human_review_candidates"
    assert report["work_finder"]["repeat_policy"] == "run_on_every_normal_distributed_loop_cycle"
    assert report["work_finder"]["safety"]["execution_approval_granted"] is False
    assert report["safety"]["candidates_executable"] is False
    assert [p.read_bytes() for p in (catalog, queue, state, runtime)] == before


def test_work_finder_reports_no_safe_work_without_fabricating_tasks(tmp_path: Path):
    root, catalog, queue, state, runtime = _fixture(tmp_path)
    (root / "core" / "agent_runtime.py").write_text(
        "def already_tested(value):\n    return value\n", encoding="utf-8"
    )
    (root / "tests" / "test_agent_runtime.py").write_text(
        "def test_already_tested():\n    assert already_tested(1) == 1\n",
        encoding="utf-8",
    )

    report = find_work(root, catalog, queue, state, runtime)

    assert report["status"] == "NO_SAFE_CANDIDATE"
    assert report["candidate_count"] == 0
    assert report["work_finder"]["cycle_status"] == "NO_SAFE_CANDIDATE"
    assert report["work_finder"]["next_action"] == "expand_allowlisted_discovery_sources"
    assert report["work_finder"]["safety"]["runtime_queue_mutated"] is False


def test_work_finder_counts_held_and_review_required_without_resuming_them(tmp_path: Path):
    root, catalog, queue, state, runtime = _fixture(tmp_path)
    _write(state, {
        "completed": [],
        "recovery_ai": {
            "schema_version": 1,
            "tasks": {
                "held-task": {"held": True},
                "review-task": {"held": False, "resume_requires_review": True},
            },
            "checkpoint": None,
        },
    })

    report = find_work(root, catalog, queue, state, runtime)

    assert report["work_finder"]["held_task_count"] == 1
    assert report["work_finder"]["resume_review_required_count"] == 1
    assert report["work_finder"]["safety"]["durable_state_mutated"] is False
