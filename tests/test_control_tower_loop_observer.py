from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.control_tower_loop_observer as observer
from core.creator_critic_runtime import build_creator_critic_loop
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



def test_observer_uses_creator_critic_only_with_explicit_local_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history = tmp_path / "observations.jsonl"
    calls: list[str] = []

    def fake_model(prompt: str) -> str:
        calls.append(prompt)
        if "CREATOR" in prompt:
            return "Add one deterministic regression test."
        return "Verdict: HOLD. Main concern: failed runtime evidence. Missing evidence: passing tests. Next safe action: run focused tests."

    monkeypatch.setenv("CREATOR_CRITIC_BASE_URL", "http://127.0.0.1:8081/v1")
    monkeypatch.setenv("CREATOR_CRITIC_MODEL", "local-test-model")
    monkeypatch.setattr(
        observer,
        "build_creator_critic_loop",
        lambda max_iterations=1: build_creator_critic_loop(
            model_call=fake_model, max_iterations=max_iterations
        ),
    )

    record_loop_observation(history, outcome("FAIL", 1))
    record = json.loads(history.read_text(encoding="utf-8").splitlines()[-1])

    assert len(calls) == 2
    assert record["creator_critic"]["configured"] is True
    assert record["creator_critic"]["rounds"] == 1
    assert record["creator_critic"]["passed"] is False
    assert record["creator_critic"]["approved_for_execution"] is False
    assert record["creator_critic"]["review_error"] is None


def test_observer_keeps_model_disabled_without_local_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history = tmp_path / "observations.jsonl"
    monkeypatch.delenv("CREATOR_CRITIC_BASE_URL", raising=False)

    record_loop_observation(history, outcome("FAIL", 1))
    record = json.loads(history.read_text(encoding="utf-8").splitlines()[-1])

    assert record["creator_critic"]["configured"] is False
    assert record["creator_critic"]["rounds"] == 0
    assert record["creator_critic"]["approved_for_execution"] is False
