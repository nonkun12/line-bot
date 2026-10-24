from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.autonomous_task_refill import build_queue


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _task(task_id: str) -> dict:
    return {"id": task_id, "instruction": "Run a focused regression test.", "allowed_paths": ["tests/test_example.py"]}


def _inputs(tmp_path: Path, *, max_tasks=4, existing=None, candidates=None):
    queue = _write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": max_tasks, "tasks": existing or []})
    catalog = _write(tmp_path / "catalog.json", {"version": 1, "max_additions_per_run": 2, "tasks": candidates or []})
    completed = _write(tmp_path / "state.json", {"version": 1, "completed": [], "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": None}})
    return queue, catalog, completed


def test_refill_adds_only_uncompleted_catalog_tasks_within_cap(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        existing=[_task("task-existing")],
        candidates=[_task("task-new-one"), _task("task-new-two"), _task("task-new-three")],
    )
    state = _write(tmp_path / "state.json", {"version": 1, "completed": ["task-new-two"], "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": None}})
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, state, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    ids = [task["id"] for task in result["tasks"]]
    assert report["added"] == 2
    assert ids == ["task-existing", "task-new-one", "task-new-three"]
    assert queue.read_text(encoding="utf-8") == queue_before


@pytest.mark.parametrize("max_tasks", [0, -1, 5, "4", True, 1.5])
def test_refill_rejects_invalid_runtime_task_limit(tmp_path: Path, max_tasks):
    queue, catalog, completed = _inputs(tmp_path, max_tasks=max_tasks, candidates=[_task("task-new-one")])
    with pytest.raises(ValueError, match="max_tasks_per_run"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


def test_refill_fails_closed_on_unsafe_path(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[{**_task("task-unsafe"), "allowed_paths": ["../secret.txt"]}],
    )
    with pytest.raises(ValueError, match="forbidden"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


@pytest.mark.parametrize(
    "path",
    [
        "tests//test_example.py",
        "./tests/test_example.py",
        "tests/../secret.py",
        "C:/secret.py",
        "c:relative-secret.py",
        "tests/\\x00bad.py",
        "tests/\x00bad.py",
    ],
)
def test_refill_rejects_ambiguous_or_traversal_paths(tmp_path: Path, path: str):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[{**_task("task-path"), "allowed_paths": [path]}],
    )
    with pytest.raises(ValueError, match="allowed path"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


@pytest.mark.parametrize(
    "path",
    [
        "../tests/test_a.py",
        "tests/../core/x.py",
        "core/ai_speaker.py",
        "scripts/x.py",
        ".github/autonomous-loop-tasks.json",
        "tests/helper.py",
        "tests/test_a.txt",
        "tests/sub/test_a.py",
        "tests",
        "TESTS/test_a.py",
        "tests/test_a.py ",
        "tests//test_a.py",
        "./tests/test_a.py",
        "uhip/tests/sub/test_a.py",
    ],
)
def test_refill_rejects_every_non_allowlisted_path(tmp_path: Path, path: str):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[{**_task("task-path"), "allowed_paths": [path]}],
    )
    with pytest.raises(ValueError, match="forbidden allowed path"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


@pytest.mark.parametrize("path", ["tests/test_a.py", "uhip/tests/test_a.py"])
def test_refill_accepts_only_allowlisted_test_files(tmp_path: Path, path: str):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[{**_task("task-path"), "allowed_paths": [path]}],
    )
    build_queue(queue, catalog, completed, tmp_path / "runtime.json")
    result = json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))
    assert result["tasks"][0]["allowed_paths"] == [path]


def test_refill_rejects_duplicate_catalog_ids(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[_task("task-same"), _task("task-same")],
    )
    with pytest.raises(ValueError, match="duplicate"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


def test_refill_rejects_duplicate_existing_queue_ids(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        existing=[_task("task-same"), _task("task-same")],
    )
    with pytest.raises(ValueError, match="duplicate"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")



def test_refill_omits_held_existing_queue_entries_without_clearing_hold(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        existing=[_task("task-held-existing")],
        candidates=[_task("task-ready-new")],
    )
    state = _write(
        tmp_path / "state.json",
        {
            "version": 1,
            "completed": [],
            "recovery_ai": {
                "schema_version": 1,
                "tasks": {"task-held-existing": {"held": True}},
                "checkpoint": None,
            },
        },
    )
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, state, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    persisted_state = json.loads(state.read_text(encoding="utf-8"))

    assert report["skipped_held_ids"] == ["task-held-existing"]
    assert report["added_ids"] == ["task-ready-new"]
    assert [task["id"] for task in result["tasks"]] == ["task-ready-new"]
    assert persisted_state["recovery_ai"]["tasks"]["task-held-existing"]["held"] is True


def test_refill_skips_recovery_ai_held_catalog_tasks(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[
            _task("task-held-one"),
            _task("task-ready-one"),
            _task("task-held-two"),
        ],
    )
    state = _write(
        tmp_path / "state.json",
        {
            "version": 1,
            "completed": [],
            "recovery_ai": {
                "schema_version": 1,
                "tasks": {
                    "task-held-one": {"held": True},
                    "task-held-two": {"held": True},
                    "task-ready-one": {"held": False},
                },
                "checkpoint": None,
            },
        },
    )
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, state, output)
    result = json.loads(output.read_text(encoding="utf-8"))

    assert report["added_ids"] == ["task-ready-one"]
    assert [task["id"] for task in result["tasks"]] == ["task-ready-one"]


def test_refill_fails_closed_when_recovery_ai_state_is_missing(tmp_path: Path):
    queue, catalog, completed = _inputs(tmp_path, candidates=[_task("task-ready-one")])
    state = _write(tmp_path / "state.json", {"version": 1, "completed": []})

    with pytest.raises(ValueError, match="Recovery AI state is missing"):
        build_queue(queue, catalog, state, tmp_path / "runtime.json")

    assert not (tmp_path / "runtime.json").exists()


@pytest.mark.parametrize("schema_version", [True, 1.0, "1", 2])
def test_refill_fails_closed_on_non_integer_or_unsupported_recovery_ai_schema(tmp_path: Path, schema_version):
    queue, catalog, completed = _inputs(tmp_path, candidates=[_task("task-ready-one")])
    state = _write(
        tmp_path / "state.json",
        {"version": 1, "completed": [], "recovery_ai": {"schema_version": schema_version, "tasks": {}, "checkpoint": None}},
    )
    output = tmp_path / "runtime.json"

    with pytest.raises(ValueError, match="Recovery AI state is invalid"):
        build_queue(queue, catalog, state, output)

    assert not output.exists()


def test_refill_fails_closed_on_invalid_recovery_ai_schema(tmp_path: Path):
    queue, catalog, completed = _inputs(tmp_path, candidates=[_task("task-ready-one")])
    state = _write(
        tmp_path / "state.json",
        {"version": 1, "completed": [], "recovery_ai": {"schema_version": 2, "tasks": {}, "checkpoint": None}},
    )

    with pytest.raises(ValueError, match="Recovery AI state is invalid"):
        build_queue(queue, catalog, state, tmp_path / "runtime.json")

    assert not (tmp_path / "runtime.json").exists()


def test_refill_fails_closed_on_malformed_recovery_ai_task_entry(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[_task("task-ready-one")],
    )
    state = _write(
        tmp_path / "state.json",
        {
            "version": 1,
            "completed": [],
            "recovery_ai": {
                "schema_version": 1,
                "tasks": {"task-bad": "not-an-object"},
                "checkpoint": None,
            },
        },
    )
    output = tmp_path / "runtime.json"

    with pytest.raises(ValueError, match="invalid Recovery AI task state"):
        build_queue(queue, catalog, state, output)

    assert not output.exists()


def test_refill_fails_closed_on_invalid_recovery_ai_held_flag(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[_task("task-ready-one")],
    )
    state = _write(
        tmp_path / "state.json",
        {
            "version": 1,
            "completed": [],
            "recovery_ai": {
                "schema_version": 1,
                "tasks": {"task-ready-one": {"held": "false"}},
                "checkpoint": None,
            },
        },
    )

    with pytest.raises(ValueError, match="held flag"):
        build_queue(queue, catalog, state, tmp_path / "runtime.json")



def test_refill_skips_tasks_requiring_post_resume_review(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        existing=[_task("task-review-existing")],
        candidates=[_task("task-review-new"), _task("task-ready-new")],
    )
    state = _write(
        tmp_path / "state.json",
        {
            "version": 1,
            "completed": [],
            "recovery_ai": {
                "schema_version": 1,
                "tasks": {
                    "task-review-existing": {
                        "held": False,
                        "resume_requires_review": True,
                    },
                    "task-review-new": {
                        "held": False,
                        "resume_requires_review": True,
                    },
                    "task-ready-new": {
                        "held": False,
                        "resume_requires_review": False,
                    },
                },
                "checkpoint": None,
            },
        },
    )
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, state, output)
    result = json.loads(output.read_text(encoding="utf-8"))

    assert report["skipped_review_ids"] == ["task-review-existing"]
    assert report["added_ids"] == ["task-ready-new"]
    assert [task["id"] for task in result["tasks"]] == ["task-ready-new"]
    persisted_state = json.loads(state.read_text(encoding="utf-8"))
    assert persisted_state["recovery_ai"]["tasks"]["task-review-existing"]["resume_requires_review"] is True
    assert persisted_state["recovery_ai"]["tasks"]["task-review-new"]["resume_requires_review"] is True


def test_refill_fails_closed_on_invalid_resume_review_flag(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[_task("task-review-invalid"), _task("task-ready-new")],
    )
    state = _write(
        tmp_path / "state.json",
        {
            "version": 1,
            "completed": [],
            "recovery_ai": {
                "schema_version": 1,
                "tasks": {
                    "task-review-invalid": {
                        "held": False,
                        "resume_requires_review": "false",
                    },
                },
                "checkpoint": None,
            },
        },
    )

    with pytest.raises(ValueError, match="resume review flag"):
        build_queue(queue, catalog, state, tmp_path / "runtime.json")

    assert not (tmp_path / "runtime.json").exists()


def test_refill_drops_completed_existing_entries_and_refills_with_new_work(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        existing=[_task("task-completed")],
        candidates=[_task("task-completed"), _task("task-next")],
    )
    state = _write(
        tmp_path / "state.json",
        {
            "version": 1,
            "completed": ["task-completed"],
            "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": None},
        },
    )
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, state, output)
    result = json.loads(output.read_text(encoding="utf-8"))

    assert report["skipped_completed_ids"] == ["task-completed"]
    assert report["retained_existing"] == 0
    assert report["added_ids"] == ["task-next"]
    assert [task["id"] for task in result["tasks"]] == ["task-next"]


def test_refill_reports_catalog_exhaustion_by_durable_state(tmp_path: Path):
    queue, catalog, _ = _inputs(
        tmp_path,
        existing=[_task("task-done")],
        candidates=[
            _task("task-done"),
            _task("task-held"),
            _task("task-review"),
        ],
    )
    state = _write(
        tmp_path / "state.json",
        {
            "version": 1,
            "completed": ["task-done"],
            "recovery_ai": {
                "schema_version": 1,
                "tasks": {
                    "task-held": {"held": True},
                    "task-review": {"resume_requires_review": True},
                },
                "checkpoint": None,
            },
        },
    )
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, state, output)

    assert report["added"] == 0
    assert report["total"] == 0
    assert report["eligible_catalog_count"] == 0
    assert report["eligible_catalog_ids"] == []
    assert report["exhaustion_reason"] == "no_eligible_catalog_tasks"
    assert report["skipped_catalog_completed_ids"] == ["task-done"]
    assert report["skipped_catalog_held_ids"] == ["task-held"]
    assert report["skipped_catalog_review_ids"] == ["task-review"]
    assert report["skipped_catalog_already_queued_ids"] == ["task-done"]
    assert json.loads(output.read_text(encoding="utf-8"))["tasks"] == []



def test_refill_prioritizes_repeated_failures_from_registered_sanitized_history(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[_task("task-alpha"), _task("task-beta"), _task("task-gamma")],
    )
    history = tmp_path / "history.jsonl"
    history.write_text("\n".join([
        json.dumps({"kind": "success", "task_id": "task-alpha", "detail": "secret should never be copied"}),
        json.dumps({"kind": "failure", "task_id": "task-beta", "detail": "raw token=secret"}),
        json.dumps({"kind": "failure", "task_id": "task-beta", "detail": "another raw exception"}),
        json.dumps({"kind": "repair", "task_id": "task-gamma"}),
        json.dumps({"kind": "failure", "task_id": "task-unknown", "detail": "must be ignored"}),
        "{malformed json",
    ]) + "\n", encoding="utf-8")
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, completed, output, history)
    result = json.loads(output.read_text(encoding="utf-8"))

    assert report["added_ids"] == ["task-beta", "task-gamma"]
    assert report["feedback_priority_scores"] == {"task-beta": 6, "task-gamma": 1}
    assert report["feedback_signal_counts"] == {
        "task-beta": {"failure": 2},
        "task-gamma": {"repair": 1},
    }
    assert "secret" not in json.dumps(result)
    assert "task-unknown" not in json.dumps(report)


def test_refill_ignores_malformed_or_unregistered_history_and_preserves_catalog_order(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[_task("task-alpha"), _task("task-beta")],
    )
    history = tmp_path / "history.jsonl"
    history.write_text("\n".join([
        json.dumps({"kind": "failure", "task_id": "task-not-registered"}),
        json.dumps({"kind": "unknown-kind", "task_id": "task-alpha"}),
        "{not json",
    ]) + "\n", encoding="utf-8")
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, completed, output, history)

    assert report["added_ids"] == ["task-alpha", "task-beta"]
    assert report["feedback_priority_scores"] == {"task-alpha": 0, "task-beta": 0}
    assert report["feedback_policy"] == "failure*3+repair-success; registered catalog IDs only"



def test_history_priority_never_bypasses_hold_completed_or_resume_review(tmp_path: Path):
    queue, catalog, _ = _inputs(
        tmp_path,
        candidates=[
            _task("task-held-high"),
            _task("task-completed-high"),
            _task("task-review-high"),
            _task("task-ready-low"),
        ],
    )
    state = _write(
        tmp_path / "state.json",
        {
            "version": 1,
            "completed": ["task-completed-high"],
            "recovery_ai": {
                "schema_version": 1,
                "tasks": {
                    "task-held-high": {"held": True},
                    "task-review-high": {"resume_requires_review": True},
                },
                "checkpoint": None,
            },
        },
    )
    history = tmp_path / "history.jsonl"
    history.write_text("\n".join([
        json.dumps({"kind": "failure", "task_id": "task-held-high"}) ,
        json.dumps({"kind": "failure", "task_id": "task-held-high"}),
        json.dumps({"kind": "failure", "task_id": "task-completed-high"}),
        json.dumps({"kind": "failure", "task_id": "task-review-high"}),
        json.dumps({"kind": "success", "task_id": "task-ready-low"}),
    ]) + "\n", encoding="utf-8")
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, state, output, history)
    result = json.loads(output.read_text(encoding="utf-8"))

    assert [task["id"] for task in result["tasks"]] == ["task-ready-low"]
    assert report["added_ids"] == ["task-ready-low"]
    # Real JSONL newlines are required: this verifies the success signal is read
    # and changes the priority score rather than silently parsing a malformed line.
    assert report["feedback_priority_scores"] == {"task-ready-low": -1}
    assert report["skipped_catalog_held_ids"] == ["task-held-high"]
    assert report["skipped_catalog_completed_ids"] == ["task-completed-high"]
    assert report["skipped_catalog_review_ids"] == ["task-review-high"]


def test_refill_ignores_history_with_invalid_utf8_without_exposing_content(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[_task("task-alpha"), _task("task-beta")],
    )
    history = tmp_path / "history.jsonl"
    history.write_bytes(b"\xff\xfe\xfa")
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, completed, output, history)

    assert report["added_ids"] == ["task-alpha", "task-beta"]
    assert report["feedback_priority_scores"] == {"task-alpha": 0, "task-beta": 0}


def test_refill_selects_exactly_four_new_catalog_tasks_when_older_tasks_are_completed(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    catalog = repo_root / ".github" / "autonomous-loop-task-catalog.json"
    catalog_data = json.loads(catalog.read_text(encoding="utf-8"))
    expected_ids = [
        "control-tower-decision-malformed-evidence-sha",
        "control-tower-decision-priority-type-boundaries",
        "task-refill-feedback-history-skips-malformed-lines",
        "proposal-generator-fails-closed-on-malformed-issue-record",
    ]
    assert catalog_data["max_additions_per_run"] == 4
    assert [task["id"] for task in catalog_data["tasks"][-4:]] == expected_ids

    queue = _write(
        tmp_path / "queue.json",
        {"version": 1, "max_tasks_per_run": 4, "tasks": []},
    )
    completed = _write(
        tmp_path / "state.json",
        {
            "version": 1,
            "completed": [
                task["id"]
                for task in catalog_data["tasks"]
                if task["id"] not in expected_ids
            ],
            "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": None},
        },
    )
    output = tmp_path / "runtime.json"
    queue_before = queue.read_text(encoding="utf-8")

    report = build_queue(queue, catalog, completed, output)
    runtime = json.loads(output.read_text(encoding="utf-8"))

    assert report["added"] == 4
    assert report["added_ids"] == expected_ids
    assert report["total"] == 4
    assert [task["id"] for task in runtime["tasks"]] == expected_ids
    assert all(task["allowed_paths"] == [f"tests/{name}"] for task, name in zip(
        runtime["tasks"],
        [
            "test_control_tower_decision.py",
            "test_control_tower_decision.py",
            "test_autonomous_task_refill.py",
            "test_autonomous_task_proposals.py",
        ],
        strict=True,
    ))
    assert queue.read_text(encoding="utf-8") != output.read_text(encoding="utf-8")
