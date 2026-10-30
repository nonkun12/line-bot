import json

import pytest

from scripts.creator_critic_state import (
    MAX_RECORDS, append_records, atomic_write, read_state, record_id, validate_records,
)


def _record(task_id="task-1", run_id="123", base=None, produced=None, stage="review"):
    base = base or "a" * 40
    produced = produced or "b" * 40
    return {
        "schema_version": 1,
        "record_id": record_id(run_id, task_id, base, stage),
        "run_id": run_id,
        "task_id": task_id,
        "base_sha": base,
        "stage": stage,
        "produced_sha": produced,
        "status": "FAIL",
        "rea_gate": "UNKNOWN",
        "recovery_action": "REVIEW",
        "proposal": {"title": "Review proposal", "rationale": "Bounded evidence summary."},
        "critic": {"verdict": "REVISE", "reason_codes": ["needs_evidence"], "evidence_refs": ["run/123#task-1"], "model_id": "pinned-model-1"},
        "created_at": "2026-10-30T00:00:00Z",
        "execution_authorized": False,
    }


def test_schema_and_task_allowlist_are_strict():
    row = _record()
    assert validate_records([row], {"task-1"}) == [row]
    for change in (
        {"unexpected": "field"},
        {"base_sha": "A" * 40},
        {"produced_sha": None},
        {"status": "UNKNOWN"},
        {"execution_authorized": True},
        {"record_id": "0" * 64},
        {"stage": "review|forged"},
    ):
        bad = {**row, **change}
        with pytest.raises(ValueError):
            validate_records([bad], {"task-1"})
    with pytest.raises(ValueError, match="registered"):
        validate_records([row], set())


def test_append_is_idempotent_bounded_and_round_trips(tmp_path):
    path = tmp_path / "history.json"
    row = _record()
    assert append_records(path, [row], {"task-1"}) == 1
    assert append_records(path, [row], {"task-1"}) == 0
    same_batch = _record(task_id="task-2", run_id="run-2")
    assert append_records(path, [same_batch, same_batch], {"task-1", "task-2"}) == 1
    assert append_records(path, [row, same_batch], {"task-1", "task-2"}) == 0
    many = [_record(task_id=f"task-{i}", run_id=f"run-{i}") for i in range(205)]
    registered = {f"task-{i}" for i in range(205)} | {"task-1"}
    # task-2/run-2 was already stored above, so its repeated identity is ignored.
    assert append_records(path, many[:200], registered) == 199
    assert append_records(path, many[200:], registered) == 5
    result = read_state(path, registered)
    assert len(result) == MAX_RECORDS
    assert result[-1]["task_id"] == "task-204"


def test_corrupt_state_fails_closed_and_preserves_file(tmp_path):
    path = tmp_path / "history.json"
    path.write_text('{"schema_version":', encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="corrupt"):
        append_records(path, [_record()], {"task-1"})
    assert path.read_bytes() == before


def test_record_id_is_stable_and_envelope_is_versioned(tmp_path):
    row = _record()
    path = tmp_path / "history.json"
    append_records(path, [row], {"task-1"})
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["schema_version"] == 1
    assert envelope["records"] == [row]
    assert row["record_id"] == record_id("123", "task-1", "a" * 40, "review")


def test_malformed_enum_values_are_rejected_as_value_error():
    row = _record()
    for key in ("status", "rea_gate", "recovery_action"):
        for value in ([], {}, None):
            with pytest.raises(ValueError):
                validate_records([{**row, key: value}], {"task-1"})
    for value in ([], {}, None):
        critic = {**row["critic"], "verdict": value}
        with pytest.raises(ValueError):
            validate_records([{**row, "critic": critic}], {"task-1"})


def test_record_id_rejects_non_string_arguments():
    for args in (("run", "task", None, "stage"), ("run", "task", [], "stage"),
                 (None, "task", "a" * 40, "stage"), ("run", {}, "a" * 40, "stage"),
                 ("run", "task", "a" * 40, None)):
        with pytest.raises(ValueError):
            record_id(*args)


def test_invalid_calendar_datetimes_are_rejected():
    for created_at in ("2026-02-30T00:00:00Z", "2026-13-01T00:00:00Z",
                       "2026-01-01T25:00:00Z", "2026-01-01T00:00:60Z"):
        with pytest.raises(ValueError):
            validate_records([{**_record(), "created_at": created_at}], {"task-1"})


def test_atomic_write_validates_records_and_registered_tasks(tmp_path):
    path = tmp_path / "history.json"
    with pytest.raises(ValueError):
        atomic_write(path, [_record()], set())
    with pytest.raises(ValueError):
        atomic_write(path, [{**_record(), "status": {"bad": True}}], {"task-1"})
    assert not path.exists()
    atomic_write(path, [_record()], {"task-1"})
    assert read_state(path, {"task-1"}) == [_record()]
