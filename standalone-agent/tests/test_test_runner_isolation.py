from pathlib import Path

from agents.test.runner import _test_env


def test_worker_test_env_overrides_production_db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_DB_PATH", "/production/chat.db")
    env = _test_env(str(tmp_path))
    assert env["ENVIRONMENT"] == "test"
    assert env["DB_TYPE"] == "sqlite"
    assert env["CHAT_DB_PATH"] == "/production/chat.db"


def test_worker_test_env_sets_scratch_db_when_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("CHAT_DB_PATH", raising=False)
    env = _test_env(str(tmp_path))
    assert env["CHAT_DB_PATH"] == str(Path(tmp_path) / ".worker-test-chat.db")
