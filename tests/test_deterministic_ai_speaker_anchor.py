"""Regression coverage for the deterministic AI Speaker queue task."""
from __future__ import annotations

import json

from core import line_development_runtime as runtime


def test_queued_ai_speaker_task_can_plan_against_real_target() -> None:
    root = runtime.worker.ROOT
    queue_path = root / ".github" / "autonomous-loop-tasks.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    task_id = "ai-speaker-empty-transcript-no-brain-call"
    assert any(task.get("id") == task_id for task in queue["tasks"])

    plan, error = runtime._deterministic_autonomous_test_plan(
        "tests/test_ai_speaker.py", task_id
    )
    assert error is None, error
    assert plan is not None
    assert plan["source"] == "deterministic_autonomous_task"
    if not plan.get("no_change"):
        change = plan["changes"][0]
        assert change["file"] == "tests/test_ai_speaker.py"
        assert (root / change["file"]).read_text(encoding="utf-8").count(change["old"]) == 1


def test_ai_speaker_anchor_plan_is_idempotent(tmp_path, monkeypatch) -> None:
    target_dir = tmp_path / "tests"
    target_dir.mkdir()
    target = target_dir / "test_ai_speaker.py"
    target.write_text(
        'def test_ai_speaker_rejects_empty_transcript() -> None:\n'
        '    try:\n'
        '        raise ValueError("empty transcript")\n'
        '    except ValueError:\n'
        '        pass\n'
        '    else:\n'
        '        raise AssertionError("empty transcript must fail closed")\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    task_id = "ai-speaker-empty-transcript-no-brain-call"
    first, error = runtime._deterministic_autonomous_test_plan(
        "tests/test_ai_speaker.py", task_id
    )
    assert error is None, error
    assert first is not None and first["no_change"] is False
    change = first["changes"][0]
    target.write_text(
        target.read_text(encoding="utf-8").replace(change["old"], change["new"], 1),
        encoding="utf-8",
    )

    second, error = runtime._deterministic_autonomous_test_plan(
        "tests/test_ai_speaker.py", task_id
    )
    assert error is None, error
    assert second == {"no_change": True, "source": "deterministic_autonomous_task"}
