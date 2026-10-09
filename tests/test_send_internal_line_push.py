import json
from io import BytesIO
from urllib.error import HTTPError, URLError

from scripts import send_internal_line_push as notifier
from scripts.send_internal_line_push import PUSH_URL, send_internal_line_push


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"ok":true}'


def test_internal_push_uses_expected_auth_payload_and_url():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    result = send_internal_line_push(
        "report",
        environ={"INTERNAL_PUSH_KEY": "secret", "DISTRIBUTED_LOOP_LINE_USER_ID": "user"},
        opener=opener,
    )
    assert result.ok is True
    assert result.http_status == 200
    assert captured["url"] == PUSH_URL
    assert captured["headers"]["X-internal-key"] == "secret"
    assert captured["payload"] == {"user_id": "user", "message": "report"}
    assert captured["timeout"] == 30


def test_missing_push_credentials_fail_without_request():
    called = False

    def opener(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("must not call endpoint without credentials")

    result = send_internal_line_push("report", environ={}, opener=opener)
    assert result.ok is False
    assert result.reason.startswith("missing_required_secrets:")
    assert called is False


def test_empty_message_fails_without_request():
    result = send_internal_line_push(
        " ",
        environ={"INTERNAL_PUSH_KEY": "secret", "DISTRIBUTED_LOOP_LINE_USER_ID": "user"},
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected request")),
    )
    assert result.reason == "empty_message"


def test_transport_failure_reason_is_reported_without_credentials():
    def opener(*_args, **_kwargs):
        raise URLError("network detail must not escape")

    result = send_internal_line_push(
        "report",
        environ={"INTERNAL_PUSH_KEY": "secret", "DISTRIBUTED_LOOP_LINE_USER_ID": "user"},
        opener=opener,
    )
    assert result.ok is False
    assert result.reason == "transport_error:URLError"


def test_http_error_reports_status_and_safe_endpoint_reason():
    def opener(*_args, **_kwargs):
        raise HTTPError(
            PUSH_URL,
            502,
            "Bad Gateway",
            {},
            BytesIO(b'{"ok":false,"error":"line channel access token rejected"}'),
        )

    result = send_internal_line_push(
        "report",
        environ={"INTERNAL_PUSH_KEY": "secret", "DISTRIBUTED_LOOP_LINE_USER_ID": "user"},
        opener=opener,
    )
    assert result.ok is False
    assert result.http_status == 502
    assert result.reason == "line_channel_access_token_rejected"


def test_cli_reports_http_status_and_missing_secret_names_without_values(monkeypatch, capsys):
    monkeypatch.setattr(notifier.sys, "argv", ["send_internal_line_push.py", "message.txt"])
    monkeypatch.setattr(notifier.Path, "read_text", lambda *_args, **_kwargs: "report")
    monkeypatch.setattr(notifier, "send_internal_line_push", lambda _message: notifier.PushResult(False, None, "missing_required_secrets:INTERNAL_PUSH_KEY,DISTRIBUTED_LOOP_LINE_USER_ID"))

    assert notifier.main() == 1
    output = capsys.readouterr().out
    assert "LINE_NOTIFICATION=FAILED" in output
    assert "LINE_NOTIFICATION_HTTP=NOT_SENT" in output
    assert "missing_required_secrets:INTERNAL_PUSH_KEY,DISTRIBUTED_LOOP_LINE_USER_ID" in output
    assert "top-secret" not in output
