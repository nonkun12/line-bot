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


def test_multi_agent_handoff_round_trip_across_distinct_workers(tmp_path):
    """Coordinator, researcher, implementer, and reviewer exchange traceable messages."""
    store = AgentCoordinationStore(tmp_path / "handoff.jsonl")
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    correlation_id = "handoff-20261025-001"

    # Coordinator assigns a bounded research task.
    store.claim_task("coordination", "control-tower", lease_seconds=600, now=now)
    store.append_event(
        "coordination", "PROGRESS", "control-tower",
        payload={
            "to": "researcher",
            "correlation_id": correlation_id,
            "message": "Identify one reproducible queue-empty cause; return evidence, not guesses.",
        },
        now=now,
    )

    # Researcher returns an evidence-bearing handoff for implementation.
    store.claim_task("research", "researcher", lease_seconds=600, now=now)
    store.append_event(
        "research", "RESULT_READY", "researcher",
        payload={
            "to": "implementer",
            "correlation_id": correlation_id,
            "finding": "Candidate selection returned no trusted task.",
            "evidence": ["candidate_count=0", "status=NO_TRUSTED_CANDIDATES"],
            "requested_action": "Add a regression test before changing runtime behavior.",
        },
        now=now + timedelta(seconds=1),
    )

    # Implementer acknowledges the same thread and hands a test artifact to review.
    store.claim_task("implementation", "implementer", lease_seconds=600, now=now)
    store.append_event(
        "implementation", "RESULT_READY", "implementer",
        payload={
            "to": "reviewer",
            "correlation_id": correlation_id,
            "artifact": "tests/test_queue_candidate_regression.py",
            "validation": "regression-test-added",
            "mutation_scope": "test-only",
        },
        now=now + timedelta(seconds=2),
    )

    # Reviewer sends an explicit decision back to the coordinator.
    store.claim_task("review", "reviewer", lease_seconds=600, now=now)
    store.append_event(
        "review", "REVIEW_FEEDBACK", "reviewer",
        payload={
            "to": "control-tower",
            "correlation_id": correlation_id,
            "decision": "HOLD",
            "reason": "Run the focused regression test and full suite before approval.",
        },
        now=now + timedelta(seconds=3),
    )
    store.append_event(
        "coordination", "RESULT_READY", "control-tower",
        payload={
            "correlation_id": correlation_id,
            "outcome": "HOLD",
            "next_step": "validate-tests",
            "merge_authorized": False,
            "deploy_authorized": False,
        },
        now=now + timedelta(seconds=4),
    )

    # A fresh reader reconstructs the complete cross-worker message chain.
    events = AgentCoordinationStore(tmp_path / "handoff.jsonl").read_events()
    messages = [
        event for event in events
        if event.event_type in {"PROGRESS", "RESULT_READY", "REVIEW_FEEDBACK"}
        and (event.payload or {}).get("correlation_id") == correlation_id
    ]
    assert [event.worker_id for event in messages] == [
        "control-tower", "researcher", "implementer", "reviewer", "control-tower"
    ]
    assert [event.payload.get("to") for event in messages[:4]] == [
        "researcher", "implementer", "reviewer", "control-tower"
    ]
    final = messages[-1].payload
    assert final["outcome"] == "HOLD"
    assert final["merge_authorized"] is False
    assert final["deploy_authorized"] is False

