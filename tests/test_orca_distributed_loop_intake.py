import pytest

from core.orca_distributed_loop_intake import build_distributed_loop_task_payload

USER_ID = "U" + "a" * 32


def test_builds_explicit_typed_distributed_loop_payload():
    payload = build_distributed_loop_task_payload(
        task_id="line-loop-1",
        request_text="分散Loopを4回、安全確認付きで実行",
        source_event_id="line-event-1",
        user_id=USER_ID,
    )

    assert payload == {
        "task_id": "line-loop-1",
        "task_type": "distributed_loop",
        "request_text": "分散Loopを4回、安全確認付きで実行",
        "max_tasks": 4,
        "source_event_id": "line-event-1",
        "user_id": USER_ID,
    }


@pytest.mark.parametrize("command,expected", [
    ("分散Loop開始", 1),
    ("分散Loopを2回、安全確認付きで実行", 2),
    ("分散Loopを4回、安全確認付きで実行", 4),
])
def test_preserves_existing_bounded_loop_semantics(command, expected):
    payload = build_distributed_loop_task_payload(
        task_id="loop-1", request_text=command,
        source_event_id="event-1", user_id=USER_ID,
    )
    assert payload["max_tasks"] == expected
    assert payload["task_type"] == "distributed_loop"


@pytest.mark.parametrize("command", [
    "こんにちは",
    "分散Loopを5回、安全確認付きで実行",
    "分散Loopを4回",
    "タスク登録: アプリ開発: sample",
    "統括AIの状況を確認",
])
def test_rejects_non_loop_or_unsafe_commands(command):
    with pytest.raises(ValueError, match="unrecognized distributed-loop command"):
        build_distributed_loop_task_payload(
            task_id="loop-1", request_text=command,
            source_event_id="event-1", user_id=USER_ID,
        )


@pytest.mark.parametrize("user_id", [None, "", "Uinvalid", "U" * 33])
def test_requires_verified_line_owner(user_id):
    with pytest.raises(ValueError, match="verified LINE user ID"):
        build_distributed_loop_task_payload(
            task_id="loop-1", request_text="分散Loop開始",
            source_event_id="event-1", user_id=user_id,
        )


@pytest.mark.parametrize("task_id,event_id", [
    ("../loop", "event-1"),
    ("loop-1", ""),
])
def test_rejects_invalid_task_metadata(task_id, event_id):
    with pytest.raises(ValueError):
        build_distributed_loop_task_payload(
            task_id=task_id, request_text="分散Loop開始",
            source_event_id=event_id, user_id=USER_ID,
        )
