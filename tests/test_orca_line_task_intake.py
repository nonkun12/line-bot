from core.orca_task_intake import build_task_payload


def test_payload_includes_verified_line_user_id():
    payload = build_task_payload(
        task_id="line-task-1",
        request_text="アプリ開発: sample",
        message_id="event-123",
        user_id="U0123456789abcdef0123456789abcdef",
    )

    assert payload == {
        "task_id": "line-task-1",
        "request_text": "アプリ開発: sample",
        "source_event_id": "event-123",
        "user_id": "U0123456789abcdef0123456789abcdef",
    }


def test_payload_omits_missing_or_invalid_user_id():
    base = {
        "task_id": "line-task-1",
        "request_text": "task",
        "source_event_id": "event-123",
    }

    assert build_task_payload("line-task-1", "task", "event-123") == base
    assert build_task_payload("line-task-1", "task", "event-123", "") == base
    assert build_task_payload("line-task-1", "task", "event-123", "Ubad/id") == base
    assert build_task_payload("line-task-1", "task", "event-123", "U" * 129) == base


def test_payload_does_not_mutate_external_data():
    payload = build_task_payload("line-task-1", "task", "event-123", "U" + "a" * 32)
    payload["user_id"] = "changed"

    assert build_task_payload("line-task-1", "task", "event-123", "U" + "a" * 32)["user_id"] == "U" + "a" * 32
