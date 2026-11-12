import pytest

from core.orca_task_intake import build_task_payload


USER = "U0123456789abcdef0123456789abcdef"


def test_payload_includes_verified_line_user_id():
    payload = build_task_payload(
        task_id="line-task-1",
        request_text="アプリ開発: sample",
        message_id="event-123",
        user_id=USER,
    )

    assert payload == {
        "task_id": "line-task-1",
        "request_text": "アプリ開発: sample",
        "source_event_id": "event-123",
        "user_id": USER,
    }


@pytest.mark.parametrize("user_id", [None, "", "Ubad/id", "U" * 129])
def test_payload_rejects_missing_or_invalid_user_id(user_id):
    with pytest.raises(ValueError, match="verified LINE user ID"):
        build_task_payload("line-task-1", "task", "event-123", user_id)


@pytest.mark.parametrize(
    "task_id,request_text,message_id",
    [
        ("../task", "task", "event-123"),
        ("line-task-1", "", "event-123"),
        ("line-task-1", "task", ""),
    ],
)
def test_payload_rejects_invalid_task_metadata(task_id, request_text, message_id):
    with pytest.raises(ValueError):
        build_task_payload(task_id, request_text, message_id, USER)


def test_payload_does_not_mutate_external_data():
    payload = build_task_payload("line-task-1", "アプリ開発: task", "event-123", USER)
    payload["user_id"] = "changed"

    assert build_task_payload("line-task-1", "task", "event-123", USER)["user_id"] == USER

@pytest.mark.parametrize("request_text", ["ordinary task", "分散Loop開始"])
def test_payload_rejects_tasks_without_explicit_app_development_prefix(request_text):
    with pytest.raises(ValueError, match="explicit アプリ開発"):
        build_task_payload("line-task-1", request_text, "event-123", USER)
