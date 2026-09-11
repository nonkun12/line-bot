from datetime import datetime, timezone

import e2e_status


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
