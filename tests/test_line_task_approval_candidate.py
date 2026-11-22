import base64
import json

import pytest

import distributed_loop_trigger as dispatcher

BASE_SHA = "a" * 40
TASK = {
    "id": "candidate-1",
    "instruction": "Run one bounded safe task.",
    "allowed_paths": ["tests/test_example.py"],
    "execution_approved": True,
}


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _contents_payload(value):
    encoded = base64.b64encode(json.dumps(value).encode("utf-8")).decode("ascii")
    return {"encoding": "base64", "content": encoded}


class _Client:
    def __init__(self, queued, catalog, state=None):
        self.queued = queued
        self.catalog = catalog
        self.state = state or {
            "goal_autopilot": {
                "tasks": [{"task_id": TASK["id"], "status": "PENDING"}]
            },
            "recovery_ai": {"tasks": {}},
        }

    def get(self, url, headers):
        if url.endswith("/commits/main"):
            return _Response({"sha": BASE_SHA})
        if "autonomous-loop-tasks.json" in url:
            return _Response(_contents_payload({"tasks": self.queued}))
        if "autonomous-loop-task-catalog.json" in url:
            return _Response(_contents_payload({"tasks": self.catalog}))
        if ".autonomous-loop-state.json" in url:
            return _Response(_contents_payload(self.state))
        raise AssertionError(f"unexpected URL: {url}")


def test_approval_candidate_requires_exactly_one_queue_entry(monkeypatch):
    monkeypatch.setattr(dispatcher, "REPO", "nonkun12/line-bot")
    result = dispatcher._fetch_task_approval_candidate(
        _Client([TASK.copy()], [TASK.copy()]), {}, TASK["id"]
    )
    assert result["catalog_match"] is True
    assert result["execution_approved"] is True


@pytest.mark.parametrize("queue", [[], [TASK.copy(), TASK.copy()]])
def test_approval_candidate_rejects_missing_or_duplicate_queue_entries(monkeypatch, queue):
    monkeypatch.setattr(dispatcher, "REPO", "nonkun12/line-bot")
    with pytest.raises(ValueError, match="not_unique_or_not_queued"):
        dispatcher._fetch_task_approval_candidate(
            _Client(queue, [TASK.copy()]), {}, TASK["id"]
        )


def test_approval_candidate_marks_queue_catalog_mismatch(monkeypatch):
    monkeypatch.setattr(dispatcher, "REPO", "nonkun12/line-bot")
    queued = {**TASK, "instruction": "Altered queued instruction"}
    result = dispatcher._fetch_task_approval_candidate(
        _Client([queued], [TASK.copy()]), {}, TASK["id"]
    )
    assert result["catalog_match"] is False


def test_approval_candidate_marks_held_goal_state(monkeypatch):
    monkeypatch.setattr(dispatcher, "REPO", "nonkun12/line-bot")
    state = {
        "goal_autopilot": {
            "tasks": [{"task_id": TASK["id"], "status": "HELD"}]
        },
        "recovery_ai": {"tasks": {}},
    }
    result = dispatcher._fetch_task_approval_candidate(
        _Client([TASK.copy()], [TASK.copy()], state=state), {}, TASK["id"]
    )
    assert result["task_held"] is True
