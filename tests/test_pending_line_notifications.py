from types import SimpleNamespace

import pytest

import app


def test_deferred_report_is_included_in_next_reply_and_deleted_after_success(monkeypatch):
    pending = {"id": 7, "message": "Run #620: NOT_RUN / queue_empty"}
    sent = []
    deleted = []

    monkeypatch.setattr(app, "get_pending_line_notification", lambda user_id: pending)
    monkeypatch.setattr(app, "_line_reply", lambda token, message: sent.append((token, message)))
    monkeypatch.setattr(app, "delete_pending_line_notification", lambda notification_id: deleted.append(notification_id) or True)

    app._reply_with_pending_notification(
        SimpleNamespace(reply_token="reply-token"),
        "user-1",
        "今回の返信本文",
    )

    assert len(sent) == 1
    assert sent[0][0] == "reply-token"
    assert "Run #620: NOT_RUN / queue_empty" in sent[0][1]
    assert "今回の返信本文" in sent[0][1]
    assert deleted == [7]


def test_deferred_report_is_preserved_when_line_reply_fails(monkeypatch):
    pending = {"id": 8, "message": "保留中の終了報告"}
    deleted = []

    monkeypatch.setattr(app, "get_pending_line_notification", lambda user_id: pending)

    def fail_reply(token, message):
        raise RuntimeError("LINE reply failed")

    monkeypatch.setattr(app, "_line_reply", fail_reply)
    monkeypatch.setattr(app, "delete_pending_line_notification", lambda notification_id: deleted.append(notification_id) or True)

    with pytest.raises(RuntimeError):
        app._reply_with_pending_notification(
            SimpleNamespace(reply_token="reply-token"),
            "user-1",
            "次の返信",
        )

    assert deleted == []
