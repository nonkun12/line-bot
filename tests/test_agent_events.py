from __future__ import annotations

import pytest

import db
from core.agent_events import AgentEvent, list_agent_events, record_agent_event


def _event(**overrides) -> AgentEvent:
    values = {
        "event_id": "evt-1",
        "task_id": "task-1",
        "agent_id": "creator",
        "role": "idea",
        "event_type": "proposal_created",
        "status": "COMPLETED",
        "request_id": "line-req-1",
        "payload": {"proposal_ref": "artifact://proposal/1", "count": 1},
    }
    values.update(overrides)
    return AgentEvent(**values)


def test_event_round_trip_and_request_correlation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB", str(tmp_path / "events.sqlite"))
    db.init_db()
    assert record_agent_event(_event()) is True
    rows = list_agent_events("task-1")
    assert len(rows) == 1
    assert rows[0]["request_id"] == "line-req-1"
    assert rows[0]["agent_id"] == "creator"
    assert rows[0]["payload"]["proposal_ref"] == "artifact://proposal/1"


def test_identical_retry_is_idempotent_but_conflict_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB", str(tmp_path / "events.sqlite"))
    db.init_db()
    event = _event()
    assert record_agent_event(event) is True
    assert record_agent_event(event) is False
    with pytest.raises(ValueError, match="different event content"):
        record_agent_event(_event(status="FAILED"))
    assert len(list_agent_events("task-1")) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "SUCCESS"},
        {"result_sha": "not-a-sha"},
        {"payload": {"nested": {"secret": "no"}}},
        {"payload": {"x": "a" * 5000}},
    ],
)
def test_invalid_event_fails_closed(overrides) -> None:
    with pytest.raises(ValueError):
        _event(**overrides)


def test_events_are_append_only_and_scoped_to_task(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB", str(tmp_path / "events.sqlite"))
    db.init_db()
    record_agent_event(_event())
    record_agent_event(_event(
        event_id="evt-2", agent_id="critic", role="reviewer",
        event_type="review_completed", status="BLOCKED", parent_task_id="task-root",
    ))
    assert [item["event_id"] for item in list_agent_events("task-1")] == ["evt-1", "evt-2"]
    assert list_agent_events("other-task") == ()
