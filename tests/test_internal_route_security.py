from flask import Flask

import app
from internal_ask_route import register_internal_ask_route


def _build_app():
    flask_app = Flask("internal-route-security")
    register_internal_ask_route(
        flask_app,
        "secret-key",
        lambda user_id, message: "ok",
    )
    return flask_app


def test_internal_push_hides_internal_exception_details(monkeypatch):
    flask_app = _build_app()

    def fail_push(user_id, text):
        raise RuntimeError("private-push-detail")

    monkeypatch.setattr(app, "_line_push", fail_push, raising=False)

    response = flask_app.test_client().post(
        "/internal/push",
        json={"user_id": "u1", "message": "test"},
        headers={"x-internal-key": "secret-key"},
    )

    assert response.status_code == 500
    assert response.get_json() == {"ok": False, "error": "internal server error"}
    assert "private-push-detail" not in response.get_data(as_text=True)


def test_internal_ai_report_hides_internal_exception_details(monkeypatch):
    flask_app = _build_app()

    monkeypatch.setattr(
        app,
        "generate_ai_secretary_report",
        lambda user_id: (_ for _ in ()).throw(RuntimeError("private-report-detail")),
        raising=False,
    )

    response = flask_app.test_client().post(
        "/internal/ai-report",
        json={"user_id": "u1"},
        headers={"x-internal-key": "secret-key"},
    )

    assert response.status_code == 500
    assert response.get_json() == {"ok": False, "error": "internal server error"}
    assert "private-report-detail" not in response.get_data(as_text=True)
