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
    initial = analyze(root, catalog, queue, state, runtime)
    candidate_id = initial["candidates"][0]["id"]
    _write(state, {"completed": [candidate_id], "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": None}})
    completed_report = analyze(root, catalog, queue, state, runtime)
    assert all(c["id"] != candidate_id for c in completed_report["candidates"])

    _write(state, {"completed": [], "recovery_ai": {"schema_version": 1, "tasks": {candidate_id: {"held": True}}, "checkpoint": None}})
    held_report = analyze(root, catalog, queue, state, runtime)
    assert all(c["id"] != candidate_id for c in held_report["candidates"])
    assert held_report["candidate_count"] == 0
    assert held_report["catalog_ids_without_runtime_plan"] == ["missing-plan"]


def test_planned_ids_include_mapping_and_explicit_plan_branches():
    source = '''
_DETERMINISTIC_AUTONOMOUS_TASK_TARGETS = {"mapped-task": "tests/test_a.py"}
def _deterministic_autonomous_test_plan(task_id, chosen):
    if task_id == "branch-task" and chosen == "tests/test_b.py":
        return {}
    return None
def unrelated(value):
    if value == "not-a-plan":
        return None
'''
    assert _planned_ids(source) == {"mapped-task", "branch-task"}


def test_analyzer_fails_closed_on_malformed_state(tmp_path: Path):
    root, catalog, queue, state, runtime = _fixture(tmp_path)
    _write(state, {"completed": [], "recovery_ai": {"schema_version": 2, "tasks": {}, "checkpoint": None}})
    with pytest.raises(ValueError, match="Recovery AI state"):
        analyze(root, catalog, queue, state, runtime)


def test_candidate_id_is_stable_when_symbol_moves(tmp_path: Path):
    root, catalog, queue, state, runtime = _fixture(tmp_path)
    before = analyze(root, catalog, queue, state, runtime)["candidates"][0]["id"]
    code = root / "core" / "agent_runtime.py"
    code.write_text("# moved line\ndef uncovered_boundary(value):\n    return value\n", encoding="utf-8")
    after = analyze(root, catalog, queue, state, runtime)["candidates"][0]["id"]
    assert after == before


def test_analyzer_discovers_unreferenced_agent_version_history_as_review_only(tmp_path: Path):
    root, catalog, queue, state, runtime = _fixture(tmp_path)
    version_source = """\
class AgentVersionRegistry:
    def current(self, agent_name):
        return None

    def history(self, agent_name):
        return tuple(self._history.get(agent_name, ()))
"""
    version_tests = """\
def test_registry_current_and_rollback_target():
    assert registry.current("developer") is not None
    assert registry.rollback_target("developer") is not None
    registry.register(version)
"""
    (root / "core" / "agent_versioning.py").write_text(version_source, encoding="utf-8")
    (root / "tests" / "test_agent_versioning.py").write_text(version_tests, encoding="utf-8")

    report = analyze(root, catalog, queue, state, runtime)
    candidates = [item for item in report["candidates"] if item["source_function"] == "AgentVersionRegistry.history"]
    assert len(candidates) == 1
    assert candidates[0]["target_test"] == "tests/test_agent_versioning.py"
    assert candidates[0]["status"] == "REVIEW_REQUIRED"
    assert candidates[0]["heuristic"] == "public-symbol-name-not-found-in-test-source; may have indirect coverage"
    assert report["safety"]["candidates_executable"] is False


def test_analyzer_suppresses_agent_version_history_when_named_in_paired_test(tmp_path: Path):
    root, catalog, queue, state, runtime = _fixture(tmp_path)
    (root / "core" / "agent_versioning.py").write_text(
        """
class AgentVersionRegistry:
    def history(self, agent_name):
        return ()
""",
        encoding="utf-8",
    )
    (root / "tests" / "test_agent_versioning.py").write_text(
        """
def test_history_is_returned_unchanged():
    assert registry.history("developer") == ()
""",
        encoding="utf-8",
    )
    report = analyze(root, catalog, queue, state, runtime)
    assert all(item["source_function"] != "AgentVersionRegistry.history" for item in report["candidates"])


def test_analyzer_discovers_unmentioned_symbols_across_the_shared_allowlist(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "core").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "core" / "control_tower.py").write_text(
        "class ControlTowerDecision:\n"
        "    def approved_task_matches(self, task):\n"
        "        return task is not None\n"
        "\n"
        "def task_hash(task_id):\n"
        "    return str(task_id)\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_control_tower.py").write_text(
        "def test_control_tower_exists():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    catalog = _write(tmp_path / "catalog.json", {"tasks": []})
    queue = _write(tmp_path / "queue.json", {"tasks": []})
    state = _write(
        tmp_path / "state.json",
        {"completed": [], "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": None}},
    )
    runtime = root / "core" / "line_development_runtime.py"
    runtime.write_text("_DETERMINISTIC_AUTONOMOUS_TASK_TARGETS = {}\n", encoding="utf-8")

    report = analyze(root, catalog, queue, state, runtime)
    assert report["candidate_count"] == 2
    assert {item["source_function"] for item in report["candidates"]} == {
        "ControlTowerDecision.approved_task_matches",
        "task_hash",
    }
    assert all(item["target_test"] == "tests/test_control_tower.py" for item in report["candidates"])
    assert report["safety"]["candidates_executable"] is False
