from __future__ import annotations

import json

import pytest

from scripts import test_agent_model_handoff as handoff


def test_live_handoff_runner_records_four_model_roles(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(
        handoff,
        "request_json",
        lambda url, timeout: {"data": [{"id": "local-test-model"}]},
    )

    def fake_model_reply(base_url, model, role, task, prior_message, correlation_id, timeout):
        calls.append((role, prior_message, correlation_id))
        return {
            "message": f"{role} received the task",
            "evidence": "message-chain-only; no runtime claims",
            "next_action": "handoff",
            "decision": "HOLD" if role == "reviewer" else "CONTINUE",
        }

    monkeypatch.setattr(handoff, "model_reply", fake_model_reply)
    report = handoff.run_test("http://127.0.0.1:8081/v1", tmp_path / "events.jsonl", 2)

    assert report["status"] == "PASS"
    assert report["mode"] == "live-model-calls"
    assert report["model_calls"] == 4
    assert [call[0] for call in calls] == ["coordinator", "researcher", "implementer", "reviewer"]
    assert calls[0][1] == ""
    assert all(call[1] for call in calls[1:])
    assert len({call[2] for call in calls}) == 1
    assert report["roles"][-1]["decision"] == "HOLD"
    assert report["safety"] == {"code_execution": False, "merge": False, "deploy": False}



def test_handoff_fails_closed_when_reviewer_passes_without_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(
        handoff,
        "request_json",
        lambda url, timeout: {"data": [{"id": "local-test-model"}]},
    )

    def fake_model_reply(base_url, model, role, task, prior_message, correlation_id, timeout):
        return {
            "message": f"{role} received the task",
            "evidence": "no execution evidence supplied",
            "next_action": "handoff",
            "decision": "PASS" if role == "reviewer" else "CONTINUE",
        }

    monkeypatch.setattr(handoff, "model_reply", fake_model_reply)
    import pytest

    with pytest.raises(AssertionError, match="Reviewer must return HOLD"):
        handoff.run_test("http://127.0.0.1:8081/v1", tmp_path / "events.jsonl", 2)



def test_model_call_failure_is_persisted_as_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(
        handoff,
        "request_json",
        lambda url, timeout: {"data": [{"id": "local-test-model"}]},
    )

    def fail_model_reply(*args, **kwargs):
        raise TimeoutError("model endpoint timed out")

    monkeypatch.setattr(handoff, "model_reply", fail_model_reply)
    ledger = tmp_path / "events.jsonl"

    import pytest
    with pytest.raises(TimeoutError, match="timed out"):
        handoff.run_test("http://127.0.0.1:8081/v1", ledger, 2)

    events = handoff.AgentCoordinationStore(ledger).read_events()
    blocked = [event for event in events if event.event_type == "BLOCKED"]
    assert len(blocked) == 1
    assert blocked[0].worker_id == "coordinator"
    assert blocked[0].payload["reason"] == "model endpoint timed out"
    assert blocked[0].payload["merge_authorized"] is False
    assert blocked[0].payload["deploy_authorized"] is False


def test_unsupported_reviewer_pass_is_recorded_as_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(
        handoff,
        "request_json",
        lambda url, timeout: {"data": [{"id": "local-test-model"}]},
    )

    def fake_model_reply(base_url, model, role, task, prior_message, correlation_id, timeout):
        return {
            "message": f"{role} received the task",
            "evidence": "no execution evidence supplied",
            "next_action": "handoff",
            "decision": "PASS" if role == "reviewer" else "CONTINUE",
        }

    monkeypatch.setattr(handoff, "model_reply", fake_model_reply)
    ledger = tmp_path / "events.jsonl"
    import pytest

    with pytest.raises(AssertionError, match="Reviewer must return HOLD"):
        handoff.run_test("http://127.0.0.1:8081/v1", ledger, 2)

    events = handoff.AgentCoordinationStore(ledger).read_events()
    blocked = [event for event in events if event.event_type == "BLOCKED"]
    assert len(blocked) == 1
    assert blocked[0].worker_id == "reviewer"
    assert blocked[0].payload["received_decision"] == "PASS"
    assert blocked[0].payload["merge_authorized"] is False
    assert blocked[0].payload["deploy_authorized"] is False



@pytest.mark.parametrize(
    "model_response",
    [
        {"choices": [{}]},
        {"choices": [None]},
        {"choices": [{"message": None}]},
        {"choices": [{"message": {"content": 123}}]},
    ],
)
def test_malformed_model_response_is_rejected(monkeypatch, model_response):
    monkeypatch.setattr(handoff, "post_json", lambda *args, **kwargs: model_response)

    with pytest.raises(ValueError):
        handoff.model_reply(
            "http://127.0.0.1:8081/v1",
            "local-test-model",
            "coordinator",
            "bounded test",
            "",
            "test-correlation",
            2,
        )
