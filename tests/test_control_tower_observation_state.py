import json

import pytest

from scripts.control_tower_observation_state import sanitize


def _record(**overrides):
    row = {
        "timestamp": "2026-10-18T00:00:00+00:00",
        "task_id": "task-1",
        "status": "PASS",
        "exit_code": 0,
        "base_sha": "a" * 40,
        "produced_sha": "b" * 40,
        "signals": [{"kind": "failure", "task_id": "task-1", "detail": "token=secret"}],
        "proposal": {"task_hash": "c" * 64, "executable": False, "approval_required": True},
    }
    row.update(overrides)
    return row


def test_sanitizer_discards_free_text_and_keeps_proposal_non_executable():
    rows = sanitize([_record()])
    serialized = json.dumps(rows)
    assert "secret" not in serialized
    assert "token=" not in serialized
    assert rows[0]["signals"][0]["detail"] == "development failure observed"
    assert rows[0]["proposal"] == {
        "task_hash": "c" * 64,
        "executable": False,
        "approval_required": True,
    }


@pytest.mark.parametrize("overrides", [
    {"status": "PASS\nINJECT"},
    {"exit_code": False},
    {"base_sha": "not-a-sha"},
    {"task_id": "../secrets"},
    {"proposal": {"task_hash": "not-a-hash"}},
])
def test_sanitizer_rejects_malformed_evidence(overrides):
    with pytest.raises(ValueError):
        sanitize([_record(**overrides)])


def test_sanitizer_bounds_history():
    rows = [_record(task_id=f"task-{i}") for i in range(250)]
    safe = sanitize(rows)
    assert len(safe) == 200
    assert safe[0]["task_id"] == "task-50"
    assert safe[-1]["task_id"] == "task-249"
