from __future__ import annotations

import json

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
