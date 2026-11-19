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

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(slack_command.threading, "Thread", ImmediateThread)

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
    assert response.get_json()["text"].startswith("🚀 開発指示を受け付けました")
    assert captured == {
        "instruction": "開発: pytestを実行",
        "user_id": "U123",
        "token": "",
        "repository": "nonkun12/line-bot",
        "authorized": True,
    }


def test_slack_ai_command_uses_shared_gateway_and_posts_result(monkeypatch):
    app = Flask(__name__)
    app.ai_gateway = type(
        "Gateway",
        (),
        {
            "handle": lambda self, request: type("Response", (), {"text": f"Slack reply: {request.message}"})()
        },
    )()
    slack_command.register_slack_command(app)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("SLACK_AI_ALLOWED_USER_IDS", "U123")

    posted = {}

    def fake_post(response_url, text):
        posted.update(response_url=response_url, text=text)

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(slack_command, "threading", type("Threading", (), {"Thread": ImmediateThread}))
    monkeypatch.setattr(slack_command, "_post_slack_response", fake_post)

    body = (
        b"user_id=U123&command=%2Fai&text=AI+NEWS%E3%81%A8%E3%83%88%E3%83%A8%E3%82%BF%E3%81%AE%E6%A0%AA%E4%BE%A1"
        b"&response_url=https%3A%2F%2Fhooks.slack.com%2Fcommands%2Ftest"
    )
    response = app.test_client().post(
        "/slack/command",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            **_signed_headers(body, "test-secret"),
        },
    )

    assert response.status_code == 200
    assert response.get_json()["text"].startswith("🔎 AI検索を受け付けました")
    assert posted == {
        "response_url": "https://hooks.slack.com/commands/test",
        "text": "Slack reply: AI NEWSとトヨタの株価",
    }
