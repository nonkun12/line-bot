import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("CHAT_DB_PATH", os.path.join(BASE_DIR, "chat.db"))


# =========================
# DB
# =========================
def get_conn():
    print("[LOG] get_conn called")
    return sqlite3.connect(DB, check_same_thread=False)


def init_db():
    print("[LOG] init_db called")
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            user_id TEXT,
            source TEXT DEFAULT 'line',
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_processed_events_event_id
        ON processed_events(event_id)
        """)
        # 旧・自前memoryテーブルはもう使わない(MCPサーバー側のSQLiteに一元化)。
        # 既存データを残したい場合はこのテーブル定義とget_memory/update_memory関数を
        # 復活させて併用することも可能。


# =========================
# 会話保存
# =========================
def save_message(user_id, role, content):
    print(f"[LOG] save_message called: user_id={user_id}, role={role}")
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO messages(user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content)
            )
    except Exception as e:
        print("DB SAVE_MESSAGE ERROR:", e)


# =========================
# 履歴
# =========================
def load_history(user_id):
    print(f"[LOG] load_history called: user_id={user_id}")
    try:
        with get_conn() as conn:
            rows = conn.execute("""
            SELECT role, content FROM messages
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 8
            """, (user_id,)).fetchall()
    except Exception as e:
        print("DB LOAD_HISTORY ERROR:", e)
        return []

    return list(reversed(rows))


# =========================
# processed_events
# =========================
def create_processed_event(event_id, user_id=None, source="line"):
    print(f"[LOG] create_processed_event called: event_id={event_id}")
    try:
        with get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO processed_events(event_id, user_id, source)
                VALUES (?, ?, ?)
                """,
                (event_id, user_id, source),
            )
            return cursor.rowcount > 0
    except Exception as e:
        print("DB CREATE_PROCESSED_EVENT ERROR:", e)
        return False


def get_processed_event(event_id):
    print(f"[LOG] get_processed_event called: event_id={event_id}")
    try:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT event_id, user_id, source, processed_at, updated_at
                FROM processed_events
                WHERE event_id=?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "event_id": row[0],
                "user_id": row[1],
                "source": row[2],
                "processed_at": row[3],
                "updated_at": row[4],
            }
    except Exception as e:
        print("DB GET_PROCESSED_EVENT ERROR:", e)
        return None


def is_processed_event(event_id):
    print(f"[LOG] is_processed_event called: event_id={event_id}")
    return get_processed_event(event_id) is not None


def update_processed_event(event_id, user_id=None, source=None):
    print(f"[LOG] update_processed_event called: event_id={event_id}")
    try:
        with get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE processed_events
                SET user_id = COALESCE(?, user_id),
                    source = COALESCE(?, source),
                    updated_at = CURRENT_TIMESTAMP
                WHERE event_id = ?
                """,
                (user_id, source, event_id),
            )
            return cursor.rowcount > 0
    except Exception as e:
        print("DB UPDATE_PROCESSED_EVENT ERROR:", e)
        return False


def delete_processed_event(event_id):
    print(f"[LOG] delete_processed_event called: event_id={event_id}")
    try:
        with get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM processed_events WHERE event_id = ?",
                (event_id,),
            )
            return cursor.rowcount > 0
    except Exception as e:
        print("DB DELETE_PROCESSED_EVENT ERROR:", e)
        return False


def list_processed_events(limit=100):
    print(f"[LOG] list_processed_events called: limit={limit}")
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT event_id, user_id, source, processed_at, updated_at
                FROM processed_events
                ORDER BY processed_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "event_id": row[0],
                    "user_id": row[1],
                    "source": row[2],
                    "processed_at": row[3],
                    "updated_at": row[4],
                }
                for row in rows
            ]
    except Exception as e:
        print("DB LIST_PROCESSED_EVENTS ERROR:", e)
        return []