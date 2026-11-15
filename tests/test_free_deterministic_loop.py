from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "free_deterministic_loop.py"
SPEC = importlib.util.spec_from_file_location("free_deterministic_loop", MODULE_PATH)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(runner)


def _task(**overrides):
    value = {
        "id": "distributed-loop-queue-progress-empty-queue-regression",
        "execution_approved": True,
        "allowed_paths": ["tests/test_distributed_loop_queue_progress.py"],
        "base_sha": "a" * 40,
    }
    value.update(overrides)
    return value


def test_unknown_task_is_rejected():
    try:
        runner.build_candidate({"id": "not-registered"}, "")
    except (KeyError, RuntimeError):
        pass
    else:
        raise AssertionError("unknown task must not be accepted")


def test_candidate_adds_exactly_one_test_and_preserves_existing_tests():
    task = _task()
    spec = runner.TASKS[task["id"]]
    original = "def test_existing():\n    assert True\n\n" + spec["anchor"] + "    queue = tmp_path / \"runtime-queue.json\"\n"
    candidate, status = runner.build_candidate(task, original)
    assert status == "PATCHED"
    before = runner.ast_test_signatures(original, "fixture.py")
    after = runner.ast_test_signatures(candidate, "fixture.py")
    assert len(after) == len(before) + 1
    assert before[0] in after


def test_existing_test_is_not_rewritten():
    task = _task()
    spec = runner.TASKS[task["id"]]
    original = "def " + spec["test_name"] + "(tmp_path):\n    assert True\n"
    candidate, status = runner.build_candidate(task, original)
    assert candidate == original
    assert status == "NO_CHANGE"


def test_ambiguous_anchor_fails_closed():
    task = _task()
    spec = runner.TASKS[task["id"]]
    original = spec["anchor"] + spec["anchor"]
    try:
        runner.build_candidate(task, original)
    except RuntimeError as exc:
        assert str(exc) == "anchor_not_unique"
    else:
        raise AssertionError("ambiguous anchor must be rejected")


def test_empty_queue_emits_no_task_evidence(tmp_path, monkeypatch):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    monkeypatch.setattr(runner.sys, "argv", ["runner", "--queue", str(queue), "--evidence", str(evidence)])
    assert runner.main() == 0
    assert json.loads(evidence.read_text(encoding="utf-8").splitlines()[0])["status"] == "NO_TASK"



def test_timeout_restores_original_source(tmp_path, monkeypatch):
    target = tmp_path / "target.py"
    original = "original source\\n"
    target.write_text("temporary candidate\\n", encoding="utf-8")

    def timeout(*args, **kwargs):
        raise runner.subprocess.TimeoutExpired(cmd="pytest", timeout=600)

    monkeypatch.setattr(runner.subprocess, "run", timeout)
    try:
        runner.run_targeted_pytest(target, original, True, "tests/test_target.py")
    except runner.subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError("pytest timeout must propagate")
    assert target.read_text(encoding="utf-8") == original



def test_nonempty_queue_requires_explicit_workflow_approval(tmp_path, monkeypatch):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"tasks": [_task()]}), encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    monkeypatch.setattr(
        runner.sys, "argv",
        ["runner", "--queue", str(queue), "--evidence", str(evidence)],
    )
    assert runner.main() == 1
    record = json.loads(evidence.read_text(encoding="utf-8").splitlines()[0])
    assert record["status"] == "BLOCKED"
    assert record["failure_reason"] == "explicit_workflow_approval_required"
