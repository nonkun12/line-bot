import pytest

import app


class FakeTimer:
    events = []

    def __init__(self, step_key):
        self.step_key = step_key
        FakeTimer.events.append(("enter", step_key))

    def __enter__(self):
        return self

    def ok(self, http_status=None):
        FakeTimer.events.append(("ok", self.step_key, http_status))

    def fail(self, http_status=None, error=None, error_location=None):
        FakeTimer.events.append(("fail", self.step_key, error_location))

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class FakeApiClient:
    def __init__(self, configuration):
        self.configuration = configuration

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class FakeMessagingApi:
    reply_calls = []
    push_calls = []
    reply_error = None
    push_error = None

    def __init__(self, api):
        self.api = api

    def reply_message(self, request):
        if self.reply_error:
            raise self.reply_error
        self.reply_calls.append(request)

    def push_message(self, request):
        if self.push_error:
            raise self.push_error
        self.push_calls.append(request)


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch):
    FakeTimer.events = []
    FakeMessagingApi.reply_calls = []
    FakeMessagingApi.push_calls = []
    FakeMessagingApi.reply_error = None
    FakeMessagingApi.push_error = None
    monkeypatch.setattr(app, "StepTimer", FakeTimer)
    monkeypatch.setattr(app, "ApiClient", FakeApiClient)
    monkeypatch.setattr(app, "MessagingApi", FakeMessagingApi)


def test_line_reply_records_actual_send_success():
    app._line_reply("reply-token", "hello")

    assert FakeMessagingApi.reply_calls
    assert ("ok", "line_out", 200) in FakeTimer.events


def test_line_reply_records_actual_send_failure():
    FakeMessagingApi.reply_error = RuntimeError("LINE reply failed")

    with pytest.raises(RuntimeError, match="LINE reply failed"):
        app._line_reply("reply-token", "hello")

    assert ("fail", "line_out", "app._line_reply") in FakeTimer.events


def test_line_push_records_actual_send_success():
    app._line_push("user-id", "hello")

    assert FakeMessagingApi.push_calls
    assert ("ok", "line_out", 200) in FakeTimer.events


def test_line_push_records_actual_send_failure():
    FakeMessagingApi.push_error = RuntimeError("LINE push failed")

    with pytest.raises(RuntimeError, match="LINE push failed"):
        app._line_push("user-id", "hello")

    assert ("fail", "line_out", "app._line_push") in FakeTimer.events
