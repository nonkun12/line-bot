import json

import pytest

from scripts.creator_critic_state import (
    MAX_RECORDS, append_records, read_state, record_id, validate_records,
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
    many = [_record(task_id=f"task-{i}", run_id=f"run-{i}") for i in range(205)]
    registered = {f"task-{i}" for i in range(205)} | {"task-1"}
    assert append_records(path, many[:200], registered) == 200
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
