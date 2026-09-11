import e2e_status
import core.request_path as request_path


def _row(status="ok", updated_at="2026-09-12T00:00:00+00:00"):
    return {
        "status": status,
        "last_success_at": updated_at if status == "ok" else None,
        "last_failure_at": updated_at if status == "error" else None,
        "last_http_status": 200 if status == "ok" else 500,
        "last_response_time_ms": 10,
        "last_error": None if status == "ok" else "boom",
        "last_error_location": None if status == "ok" else "agent",
        "updated_at": updated_at,
    }


def test_primary_e2e_order_is_line_core_agent_line():
    assert e2e_status.STEP_ORDER == ["line_in", "core", "agent", "line_out"]
    assert "n8n_webhook" not in e2e_status.STEP_ORDER
    assert "internal_ask" not in e2e_status.STEP_ORDER


def test_n8n_is_auxiliary_only():
    assert "n8n_webhook" in e2e_status.AUXILIARY_STEP_ORDER
    assert "n8n_workflow" in e2e_status.AUXILIARY_STEP_ORDER
    assert "internal_ask" in e2e_status.AUXILIARY_STEP_ORDER
    assert "internal_push" in e2e_status.AUXILIARY_STEP_ORDER


def test_legacy_line_bot_record_maps_to_line_in():
    assert e2e_status._canonical_step_key("line_bot") == "line_in"
    assert e2e_status._canonical_step_key("core") == "core"


def test_primary_status_ignores_auxiliary_success(monkeypatch):
    rows = {
        "line_in": _row(),
        "core": _row(),
        "agent": _row(),
        "line_out": _row(),
        "n8n_webhook": _row(),
        "internal_ask": _row(),
    }
    monkeypatch.setattr(e2e_status, "_get_all_steps", lambda: rows)
    payload = e2e_status.get_e2e_status()

    assert payload["overall"] == "ok"
    assert [step["key"] for step in payload["steps"]] == [
        "line_in", "core", "agent", "line_out"
    ]
    assert any(step["key"] == "n8n_webhook" for step in payload["auxiliary"])


def test_primary_error_stops_without_using_n8n(monkeypatch):
    rows = {
        "line_in": _row(),
        "core": _row(status="error"),
        "n8n_webhook": _row(),
        "internal_ask": _row(),
        "line_out": _row(),
    }
    monkeypatch.setattr(e2e_status, "_get_all_steps", lambda: rows)
    payload = e2e_status.get_e2e_status()

    assert payload["overall"] == "error"
    assert payload["steps"][1]["key"] == "core"
    assert payload["steps"][1]["state"] == "error"
    assert payload["steps"][2]["state"] == "not_reached"


def test_core_then_agent_are_recorded_in_order(monkeypatch):
    events = []

    class FakeTimer:
        def __init__(self, step_key):
            self.step_key = step_key

        def __enter__(self):
            events.append(("enter", self.step_key))
            return self

        def ok(self, http_status=None):
            events.append(("ok", self.step_key))

        def fail(self, http_status=None, error=None, error_location=None):
            events.append(("fail", self.step_key))

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    def fake_supervisor(initial):
        events.append(("supervisor", initial["raw_message"]))
        return initial

    class FakeGraph:
        def invoke(self, state):
            events.append(("agent_invoke", state["raw_message"]))
            return {"final_reply": "test reply"}

    monkeypatch.setattr(request_path, "StepTimer", FakeTimer)
    monkeypatch.setattr(request_path, "supervisor_node", fake_supervisor)
    monkeypatch.setattr(request_path, "build_current_core_graph", lambda: FakeGraph())

    result = request_path.run_core_request("u1", "テスト", channel="line")

    assert result["final_reply"] == "test reply"
    assert [name for name, _ in events if name in {"supervisor", "agent_invoke"}] == [
        "supervisor", "agent_invoke"
    ]
    assert events.index(("ok", "agent")) < events.index(("ok", "core"))
