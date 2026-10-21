from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.control_tower_loop_observer import record_loop_observation


def outcome(status: str = "PASS", exit_code: int = 0) -> dict[str, object]:
    return {
        "task_id": "task-1",
        "status": status,
        "exit_code": exit_code,
        "base_sha": "a" * 40,
        "produced_sha": "b" * 40,
        "failure_reason": "do not persist raw exception text",
    }


def test_observer_persists_sanitized_non_executable_proposal(tmp_path: Path) -> None:
    history = tmp_path / "observations.jsonl"

    result = record_loop_observation(history, outcome())

    assert result["recorded"] is True
    assert result["proposal_executable"] is False
    records = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["task_id"] == "task-1"
    assert records[0]["status"] == "PASS"
    if records[0]["proposal"] is not None:
        assert records[0]["proposal"]["executable"] is False
        assert records[0]["proposal"]["approval_required"] is True
        assert "do not persist raw exception text" not in json.dumps(records[0])


def test_observer_records_failed_loop_without_raw_error(tmp_path: Path) -> None:
    history = tmp_path / "observations.jsonl"
    record_loop_observation(history, outcome("FAIL", 1))
    record = json.loads(history.read_text(encoding="utf-8").splitlines()[-1])

    assert record["status"] == "FAIL"
    assert all("raw exception" not in signal["detail"] for signal in record["signals"])



def test_boolean_exit_code_cannot_be_misclassified_as_success(tmp_path: Path) -> None:
    history = tmp_path / "observations.jsonl"

    record_loop_observation(history, outcome("PASS", False))
    record = json.loads(history.read_text(encoding="utf-8").splitlines()[-1])

    assert record["status"] == "PASS"
    assert record["exit_code"] is None
    assert record["observation_count"] > 0



def test_malformed_status_type_fails_closed_without_crashing(tmp_path: Path) -> None:
    history = tmp_path / "observations.jsonl"

    record_loop_observation(history, {**outcome(), "status": ["PASS"]})
    record = json.loads(history.read_text(encoding="utf-8").splitlines()[-1])

    assert record["exit_code"] == 0
    assert record["observation_count"] > 0

def test_invalid_sha_evidence_is_not_persisted_as_a_valid_fingerprint(tmp_path: Path) -> None:
    history = tmp_path / "observations.jsonl"

    record_loop_observation(
        history,
        {**outcome(), "base_sha": "not-a-sha", "produced_sha": "g" * 40},
    )
    record = json.loads(history.read_text(encoding="utf-8").splitlines()[-1])

    assert record["base_sha"] is None
    assert record["produced_sha"] is None

def test_malformed_history_fails_closed_and_preserves_original(tmp_path: Path) -> None:
    history = tmp_path / "observations.jsonl"
    history.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="control_tower_history_unreadable"):
        record_loop_observation(history, outcome())

    assert history.read_text(encoding="utf-8") == "{not-json}\n"


def test_history_is_bounded_to_200_records(tmp_path: Path) -> None:
    history = tmp_path / "observations.jsonl"
    for i in range(205):
        record_loop_observation(history, {**outcome(), "task_id": f"task-{i}"})

    records = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 200
    assert records[0]["task_id"] == "task-5"
    assert records[-1]["task_id"] == "task-204"
