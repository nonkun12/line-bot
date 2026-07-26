import sqlite3

DB = "chat.db"


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