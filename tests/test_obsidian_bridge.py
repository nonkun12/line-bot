from flask import Flask

from core.obsidian_bridge import OBSIDIAN_JOB_TYPE, enqueue_obsidian_request


def test_enqueue_obsidian_request_accepts_only_explicit_commands(monkeypatch):
    captured = {}

    def fake_create_job(user_id, message, **kwargs):
        captured.update(user_id=user_id, message=message, kwargs=kwargs)
        return 42

    monkeypatch.setattr("core.obsidian_bridge.create_job", fake_create_job)

    job_id = enqueue_obsidian_request("U1", "Obsidianに保存 notes/todo.md: hello")

    assert job_id == 42
    assert captured["user_id"] == "U1"
    assert captured["message"] == "Obsidianに保存 notes/todo.md: hello"
    assert captured["kwargs"]["job_type"] == OBSIDIAN_JOB_TYPE
    assert captured["kwargs"]["source"] == "line"
    assert captured["kwargs"]["max_retries"] == 3


def test_enqueue_obsidian_request_rejects_non_obsidian():
    import pytest
    with pytest.raises(ValueError, match="explicit Obsidian"):
        enqueue_obsidian_request("U1", "こんにちは")


def test_enqueue_obsidian_request_rejects_oversized_message():
    import pytest
    with pytest.raises(ValueError, match="4000"):
        enqueue_obsidian_request("U1", "Obsidian一覧" + ("x" * 4000))
