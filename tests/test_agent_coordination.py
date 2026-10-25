from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from core.agent_coordination import AgentCoordinationStore


def test_ledger_persists_events_and_filters_by_task(tmp_path):
    store = AgentCoordinationStore(tmp_path / "events.jsonl")
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    store.claim_task("task-1", "worker-a", lease_seconds=60, now=now)
    store.append_event("task-1", "PROGRESS", "worker-a", payload={"step": "inspect"}, now=now)
    store.claim_task("task-2", "worker-b", lease_seconds=60, now=now)
    store.append_event("task-2", "NEED_INPUT", "worker-b", payload={"question": "scope"}, now=now)

    assert [event.event_type for event in store.read_events("task-1")] == ["TASK_CLAIMED", "PROGRESS"]
    assert len(AgentCoordinationStore(tmp_path / "events.jsonl").read_events()) == 4


def test_live_lease_prevents_duplicate_claim(tmp_path):
    store = AgentCoordinationStore(tmp_path / "events.jsonl")
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    store.claim_task("task-1", "worker-a", lease_seconds=60, now=now)

    with pytest.raises(RuntimeError, match="already leased"):
        store.claim_task("task-1", "worker-b", lease_seconds=60, now=now)


def test_expired_lease_can_be_reclaimed_but_old_worker_is_rejected(tmp_path):
    store = AgentCoordinationStore(tmp_path / "events.jsonl")
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    store.claim_task("task-1", "worker-a", lease_seconds=30, now=now)
    store.claim_task("task-1", "worker-b", lease_seconds=60, now=now + timedelta(seconds=31))

    with pytest.raises(PermissionError, match="does not own"):
        store.append_event("task-1", "RESULT_READY", "worker-a", now=now + timedelta(seconds=32))

    store.append_event("task-1", "RESULT_READY", "worker-b", payload={"sha": "abc"}, now=now + timedelta(seconds=32))


def test_expired_worker_cannot_publish_result_before_reclaim(tmp_path):
    store = AgentCoordinationStore(tmp_path / "events.jsonl")
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    store.claim_task("task-1", "worker-a", lease_seconds=10, now=now)

    with pytest.raises(PermissionError, match="lease expired"):
        store.append_event("task-1", "RESULT_READY", "worker-a", now=now + timedelta(seconds=11))


def test_released_task_can_be_claimed_by_another_worker(tmp_path):
    store = AgentCoordinationStore(tmp_path / "events.jsonl")
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    store.claim_task("task-1", "worker-a", lease_seconds=60, now=now)
    store.append_event("task-1", "TASK_RELEASED", "worker-a", now=now + timedelta(seconds=1))
    store.claim_task("task-1", "worker-b", lease_seconds=60, now=now + timedelta(seconds=2))

    assert store.read_events("task-1")[-1].worker_id == "worker-b"


def test_claim_is_process_serialized_so_only_one_worker_wins(tmp_path):
    store = AgentCoordinationStore(tmp_path / "events.jsonl")
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

    def claim(worker_id: str) -> str:
        try:
            store.claim_task("task-1", worker_id, lease_seconds=60, now=now)
            return "won"
        except RuntimeError:
            return "busy"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, [f"worker-{i}" for i in range(8)]))

    assert results.count("won") == 1
    assert results.count("busy") == 7
    assert len([event for event in store.read_events("task-1") if event.event_type == "TASK_CLAIMED"]) == 1


@pytest.mark.parametrize(
    ("event_type", "worker_id", "payload"),
    [
        ("UNKNOWN", "worker-a", None),
        ("PROGRESS", "", None),
        ("PROGRESS", "worker-a", {"not_json": object()}),
    ],
)
def test_invalid_event_is_rejected(tmp_path, event_type, worker_id, payload):
    store = AgentCoordinationStore(tmp_path / "events.jsonl")
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    store.claim_task("task-1", "worker-a", lease_seconds=60, now=now)

    with pytest.raises(ValueError):
        store.append_event("task-1", event_type, worker_id, payload=payload, now=now)



def test_claim_event_cannot_bypass_atomic_lease_api(tmp_path):
    store = AgentCoordinationStore(tmp_path / "events.jsonl")

    with pytest.raises(ValueError, match="use claim_task"):
        store.append_event(
            "task-1",
            "TASK_CLAIMED",
            "worker-a",
            payload={"lease_until": "pretend"},
        )


def test_naive_timestamp_is_rejected(tmp_path):
    store = AgentCoordinationStore(tmp_path / "events.jsonl")
    naive = datetime(2026, 10, 25, 12, 0)

    with pytest.raises(ValueError, match="timezone-aware"):
        store.claim_task("task-1", "worker-a", now=naive)
