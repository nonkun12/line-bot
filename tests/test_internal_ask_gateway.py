from flask import Flask

from internal_ask_route import register_internal_ask_route


def test_internal_ask_uses_channel_independent_gateway():
    app = Flask(__name__)
    seen = {}

    def handler(request):
        seen["request"] = request
        return f"echo:{request.message}"

    register_internal_ask_route(app, "secret", handler)
    client = app.test_client()

    response = client.post(
        "/internal/ask",
        json={"user_id": "u1", "message": "hello", "channel": "web"},
        headers={"x-internal-key": "secret"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "reply": "echo:hello"}
    assert seen["request"].user_id == "u1"
    assert seen["request"].message == "hello"
    assert seen["request"].channel == "web"
    assert seen["request"].metadata["transport"] == "internal_ask"


def test_internal_ask_defaults_channel_to_line():
    app = Flask(__name__)
    seen = {}

    def handler(request):
        seen["request"] = request
        return "ok"

    register_internal_ask_route(app, "secret", handler)
    client = app.test_client()

    response = client.post(
        "/internal/ask",
        json={"user_id": "u1", "message": "hello"},
        headers={"x-internal-key": "secret"},
    )

    assert response.status_code == 200
    assert seen["request"].channel == "line"
