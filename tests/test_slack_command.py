import hashlib
import hmac
import time

from flask import Flask

import slack_command


def _signed_headers(body: bytes, secret: str):
    timestamp = str(int(time.time()))
    base = f"v0:{timestamp}:".encode("utf-8") + body
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": f"v0={digest}",
    }


def test_verify_signature_accepts_fresh_request():
    secret = "test-secret"
    body = b"user_id=U123&text=hello"
    headers = _signed_headers(body, secret)
    assert slack_command._verify_signature(
        body,
        headers["X-Slack-Request-Timestamp"],
        headers["X-Slack-Signature"],
        secret,
    )


def test_verify_signature_rejects_stale_request():
    secret = "test-secret"
    body = b"user_id=U123&text=hello"
    timestamp = str(int(time.time()) - 301)
    base = f"v0:{timestamp}:".encode("utf-8") + body
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    assert not slack_command._verify_signature(body, timestamp, f"v0={digest}", secret)


def test_slack_command_dispatches_verified_authorized_user(monkeypatch):
    app = Flask(__name__)
    slack_command.register_slack_command(app)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("SLACK_DEV_ALLOWED_USER_IDS", "U123")

    captured = {}

    def fake_dispatch(instruction, *, user_id, token, repository, authorized):
        captured.update(
            instruction=instruction,
            user_id=user_id,
            token=token,
            repository=repository,
            authorized=authorized,
        )
        return "accepted"

    monkeypatch.setattr(slack_command, "dispatch_development_workflow", fake_dispatch)
    body = b"user_id=U123&text=%E9%96%8B%E7%99%BA%3A+pytest%E3%82%92%E5%AE%9F%E8%A1%8C"
    client = app.test_client()
    response = client.post(
        "/slack/command",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", **_signed_headers(body, "test-secret")},
    )

    assert response.status_code == 200
    assert response.get_json()["text"] == "accepted"
    assert captured == {
        "instruction": "pytestを実行",
        "user_id": "U123",
        "token": "",
        "repository": "nonkun12/line-bot",
        "authorized": True,
    }
