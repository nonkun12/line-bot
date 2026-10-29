from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.catalog_exhaustion_analyzer import analyze, _planned_ids


def _write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _fixture(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "core").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "core" / "agent_runtime.py").write_text("def uncovered_boundary(value):\n    return value\n", encoding="utf-8")
    (root / "tests" / "test_agent_runtime.py").write_text("def test_existing():\n    assert True\n", encoding="utf-8")
    # Other allowlisted targets are absent and therefore skipped.
    catalog = _write(tmp_path / "catalog.json", {"tasks": [{"id": "known-task"}]})
    queue = _write(tmp_path / "queue.json", {"tasks": []})
    state = _write(tmp_path / "state.json", {"completed": [], "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": None}})
    runtime = root / "core" / "line_development_runtime.py"
    runtime.write_text('_DETERMINISTIC_AUTONOMOUS_TASK_TARGETS = {"known-task": "tests/test_agent_runtime.py"}\n', encoding="utf-8")
    return root, catalog, queue, state, runtime


def test_analyzer_emits_review_only_candidate_without_mutating_inputs(tmp_path: Path):
    root, catalog, queue, state, runtime = _fixture(tmp_path)
    before = [p.read_bytes() for p in (catalog, queue, state, runtime)]
    report = analyze(root, catalog, queue, state, runtime)
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["candidate_count"] == 1
    candidate = report["candidates"][0]
    assert candidate["target_test"] == "tests/test_agent_runtime.py"
    assert candidate["evidence"] == "core/agent_runtime.py:1"
    assert candidate["status"] == "REVIEW_REQUIRED"
    assert candidate["fingerprint"]
    assert report["safety"]["candidates_executable"] is False
    assert report["catalog_ids_without_runtime_plan"] == []
    assert [p.read_bytes() for p in (catalog, queue, state, runtime)] == before


def test_analyzer_is_deterministic(tmp_path: Path):
    root, catalog, queue, state, runtime = _fixture(tmp_path)
    assert analyze(root, catalog, queue, state, runtime) == analyze(root, catalog, queue, state, runtime)


def test_analyzer_reports_catalog_ids_without_plan_and_excludes_held_or_completed(tmp_path: Path):
    root, catalog, queue, state, runtime = _fixture(tmp_path)
    _write(catalog, {"tasks": [{"id": "known-task"}, {"id": "missing-plan"}]})
    _write(state, {"completed": ["known-task"], "recovery_ai": {"schema_version": 1, "tasks": {"review-coverage-gap-0": {"held": True}}, "checkpoint": None}})
    report = analyze(root, catalog, queue, state, runtime)
    assert report["catalog_ids_without_runtime_plan"] == ["missing-plan"]
    assert all(c["id"] != "known-task" for c in report["candidates"])


def test_planned_ids_come_only_from_runtime_mapping():
    assert _planned_ids('_DETERMINISTIC_AUTONOMOUS_TASK_TARGETS = {"a": "tests/test_a.py"}') == {"a"}
    assert _planned_ids("unrelated = {'not-a-plan': 1}") == set()


def test_analyzer_fails_closed_on_malformed_state(tmp_path: Path):
    root, catalog, queue, state, runtime = _fixture(tmp_path)
    _write(state, {"completed": [], "recovery_ai": {"schema_version": 2, "tasks": {}, "checkpoint": None}})
    with pytest.raises(ValueError, match="Recovery AI state"):
        analyze(root, catalog, queue, state, runtime)
