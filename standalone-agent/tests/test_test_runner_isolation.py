from pathlib import Path

from agents.test.runner import _test_env


def test_worker_test_env_overrides_production_db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_DB_PATH", "/production/chat.db")
    env, scratch_db = _test_env(str(tmp_path))
    assert env["ENVIRONMENT"] == "test"
    assert env["DB_TYPE"] == "sqlite"
    assert env["CHAT_DB_PATH"] == scratch_db
    assert scratch_db != "/production/chat.db"
    assert Path(scratch_db).exists()


def test_worker_test_env_uses_unique_scratch_db(tmp_path, monkeypatch):
    monkeypatch.delenv("CHAT_DB_PATH", raising=False)
    _, first_db = _test_env(str(tmp_path))
    _, second_db = _test_env(str(tmp_path))
    assert first_db != second_db
    assert Path(first_db).exists()
    assert Path(second_db).exists()
