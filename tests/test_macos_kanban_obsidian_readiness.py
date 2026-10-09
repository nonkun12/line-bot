import sqlite3
from pathlib import Path

from scripts import macos_kanban_obsidian_readiness as readiness


def test_missing_kanban_database_is_warning_and_is_not_created(tmp_path: Path):
    db_path = tmp_path / "kanban.db"

    status, detail = readiness.check_kanban_database(db_path)

    assert status == "WARN"
    assert "not present" in detail
    assert not db_path.exists()


def test_kanban_database_health_check_is_read_only(tmp_path: Path):
    db_path = tmp_path / "kanban.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        conn.executemany(
            "INSERT INTO tasks(id, status) VALUES (?, ?)",
            [("task-1", "ready"), ("task-2", "blocked"), ("task-3", "ready")],
        )

    before = db_path.stat().st_size
    status, detail = readiness.check_kanban_database(db_path)

    assert status == "PASS"
    assert "quick_check=ok" in detail
    assert "tasks=3" in detail
    assert "blocked:1" in detail
    assert "ready:2" in detail
    assert db_path.stat().st_size == before


def test_kanban_database_with_missing_tasks_table_fails_closed(tmp_path: Path):
    db_path = tmp_path / "kanban.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE unrelated (id INTEGER)")

    status, detail = readiness.check_kanban_database(db_path)

    assert status == "FAIL"
    assert "tasks table is missing" in detail


def test_load_env_file_ignores_comments_and_strips_quotes(tmp_path: Path):
    env_path = tmp_path / "bridge.env"
    env_path.write_text(
        '# ignored\nexport OBSIDIAN_BRIDGE_KEY="not-for-logs"\n'
        "OBSIDIAN_VAULT_PATH='/tmp/my vault'\n",
        encoding="utf-8",
    )

    loaded = readiness.load_env_file(env_path)

    assert loaded == {
        "OBSIDIAN_BRIDGE_KEY": "not-for-logs",
        "OBSIDIAN_VAULT_PATH": "/tmp/my vault",
    }
