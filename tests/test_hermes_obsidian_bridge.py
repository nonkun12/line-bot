from core.hermes_obsidian_bridge import (
    enqueue_verified_hermes_result,
    is_verified_hermes_result,
)


def test_verified_hermes_pass_is_eligible():
    result = {
        "source": "hermes-kanban",
        "status": "PASS",
        "verified": True,
        "auto_apply_patch": False,
        "auto_deploy": False,
    }
    assert is_verified_hermes_result(result) is True


def test_hermes_fail_is_blocked():
    result = {
        "source": "hermes-kanban",
        "status": "FAIL",
        "verified": True,
        "auto_apply_patch": False,
        "auto_deploy": False,
    }
    assert is_verified_hermes_result(result) is False


def test_hermes_blocked_is_blocked():
    result = {
        "source": "hermes-kanban",
        "status": "BLOCKED",
        "verified": True,
        "auto_apply_patch": False,
        "auto_deploy": False,
    }
    assert is_verified_hermes_result(result) is False


def test_unverified_or_unsafe_result_is_blocked():
    assert is_verified_hermes_result(
        {
            "source": "hermes-kanban",
            "status": "PASS",
            "verified": False,
            "auto_apply_patch": False,
            "auto_deploy": False,
        }
    ) is False
    assert is_verified_hermes_result(
        {
            "source": "hermes-kanban",
            "status": "PASS",
            "verified": True,
            "auto_apply_patch": True,
            "auto_deploy": False,
        }
    ) is False


def test_verified_pass_is_handed_to_existing_obsidian_queue(monkeypatch):
    captured = {}

    def fake_enqueue(user_id, message):
        captured["user_id"] = user_id
        captured["message"] = message
        return 123

    monkeypatch.setattr(
        "core.hermes_obsidian_bridge.enqueue_obsidian_request",
        fake_enqueue,
    )
    result = {
        "source": "hermes-kanban",
        "status": "PASS",
        "verified": True,
        "auto_apply_patch": False,
        "auto_deploy": False,
        "task_id": "t_smoke",
        "summary": "Completed without changes needed.",
    }
    assert enqueue_verified_hermes_result("user-1", result) == 123
    assert captured == {
        "user_id": "user-1",
        "message": "Obsidianに追記 LINE-Inbox.md: Hermes PASS t_smoke: Completed without changes needed.",
    }


def test_blocked_result_never_reaches_queue(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("queue must not be called")

    monkeypatch.setattr(
        "core.hermes_obsidian_bridge.enqueue_obsidian_request",
        fail_if_called,
    )
    result = {
        "source": "hermes-kanban",
        "status": "BLOCKED",
        "verified": True,
        "auto_apply_patch": False,
        "auto_deploy": False,
        "task_id": "t_blocked",
        "summary": "blocked",
    }
    try:
        enqueue_verified_hermes_result("user-1", result)
    except ValueError:
        pass
    else:
        raise AssertionError("blocked result must be rejected")
