from datetime import datetime, timedelta, timezone

from core import line_development_context as context


def test_context_round_trips_per_user_and_expires(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_DB_PATH", str(tmp_path / "chat.db"))
    now = datetime(2026, 11, 5, 7, 0, tzinfo=timezone.utc)

    assert context.save_last_instruction("U1", "Improve the LINE router", "req-1", now=now)
    assert context.get_last_instruction("U1", now=now) == {
        "instruction": "Improve the LINE router",
        "request_id": "req-1",
        "accepted_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=24)).isoformat(),
    }
    assert context.get_last_instruction("U2", now=now) is None
    assert context.get_last_instruction("U1", now=now + timedelta(hours=24)) is None


def test_new_accepted_request_replaces_only_same_users_context(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_DB_PATH", str(tmp_path / "chat.db"))
    now = datetime(2026, 11, 5, 7, 0, tzinfo=timezone.utc)

    context.save_last_instruction("U1", "first", "req-1", now=now)
    context.save_last_instruction("U2", "other user", "req-2", now=now)
    context.save_last_instruction("U1", "second", "req-3", now=now + timedelta(minutes=1))

    assert context.get_last_instruction("U1", now=now)["instruction"] == "second"
    assert context.get_last_instruction("U2", now=now)["instruction"] == "other user"


def test_invalid_context_is_not_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_DB_PATH", str(tmp_path / "chat.db"))

    assert not context.save_last_instruction("", "instruction", "req")
    assert not context.save_last_instruction("U1", "", "req")
    assert not context.save_last_instruction("U1", "instruction", "")
    assert not context.save_last_instruction("U1", "x" * 2001, "req")
    assert context.get_last_instruction("U1") is None


def test_missing_context_table_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_DB_PATH", str(tmp_path / "empty.db"))

    assert context.get_last_instruction("U1") is None
