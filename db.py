import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("CHAT_DB_PATH", os.path.join(BASE_DIR, "chat.db"))
STALE_JOB_SECONDS = int(os.environ.get("JOB_STALE_SECONDS", "1800"))


def get_conn():
    print("[LOG] get_conn called")
    return sqlite3.connect(DB, check_same_thread=False)


def _table_columns(conn, table_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def _ensure_column(conn, table_name, column_name, definition):
    if column_name not in _table_columns(conn, table_name):
        conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )


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
        conn.execute("""
        CREATE TABLE IF NOT EXISTS approvals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            approved INTEGER DEFAULT 0,
            rejected INTEGER DEFAULT 0
        )
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_approvals_user_id
        ON approvals(user_id)
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            job_type TEXT NOT NULL DEFAULT 'ai_task',
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            last_error TEXT,
            result TEXT,
            source TEXT NOT NULL DEFAULT 'line',
            parent_job_id INTEGER,
            claimed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Migrate databases created before the Worker fields existed.
        _ensure_column(conn, "jobs", "source", "TEXT NOT NULL DEFAULT 'line'")
        _ensure_column(conn, "jobs", "parent_job_id", "INTEGER")
        _ensure_column(conn, "jobs", "claimed_at", "TIMESTAMP")

        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at
        ON jobs(status, created_at)
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_user_id
        ON jobs(user_id)
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_claimed_at
        ON jobs(status, claimed_at)
        """")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS job_checkpoints(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            step_name TEXT NOT NULL,
            step_status TEXT NOT NULL,
            output_snapshot TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_job_checkpoints_job_id
        ON job_checkpoints(job_id, id)
        """)


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
# Jobs
# =========================
def create_job(
    user_id,
    message,
    job_type="ai_task",
    source="line",
    parent_job_id=None,
    max_retries=3,
):
    """夜間/非同期実行用のJobをpending状態で登録する。"""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO jobs(
                user_id, job_type, message, status,
                max_retries, source, parent_job_id
            )
            VALUES (?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                user_id,
                job_type,
                message,
                max_retries,
                source,
                parent_job_id,
            ),
        )
        return cursor.lastrowid


def get_job(job_id):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, user_id, job_type, message, status, retry_count,
                   max_retries, last_error, result, source, parent_job_id,
                   claimed_at, created_at, updated_at
            FROM jobs WHERE id=?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    keys = (
        "id", "user_id", "job_type", "message", "status", "retry_count",
        "max_retries", "last_error", "result", "source", "parent_job_id",
        "claimed_at", "created_at", "updated_at",
    )
    return dict(zip(keys, row))


def requeue_stale_jobs(stale_seconds=STALE_JOB_SECONDS):
    """Stale running jobs are logged as stalled then made runnable again."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id FROM jobs
            WHERE status='running'
              AND claimed_at IS NOT NULL
              AND (julianday('now') - julianday(claimed_at)) * 86400 > ?
            ORDER BY id
            """,
            (stale_seconds,),
        ).fetchall()
        job_ids = [row[0] for row in rows]
        for job_id in job_ids:
            conn.execute(
                """
                UPDATE jobs
                SET status='pending', claimed_at=NULL,
                    last_error='worker lease expired; job requeued',
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='running'
                """,
                (job_id,),
            )
    for job_id in job_ids:
        save_checkpoint(
            job_id,
            "worker_recovery",
            "stalled",
            "worker lease expired; requeued",
        )
    return job_ids


def claim_pending_job():
    """最古のpending Jobを排他的に1件だけrunningへ移す。"""
    requeue_stale_jobs()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM jobs WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        job_id = row[0]
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status='running', claimed_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='pending'
            """,
            (job_id,),
        )
        if cursor.rowcount != 1:
            return None
    return get_job(job_id)


def update_job(
    job_id,
    status=None,
    result=None,
    last_error=None,
    retry_count=None,
    claimed_at=None,
    clear_claimed_at=False,
):
    """Job状態を部分更新する。"""
    fields = []
    values = []
    if status is not None:
        fields.append("status=?")
        values.append(status)
    if result is not None:
        fields.append("result=?")
        values.append(result)
    if last_error is not None:
        fields.append("last_error=?")
        values.append(last_error)
    if retry_count is not None:
        fields.append("retry_count=?")
        values.append(retry_count)
    if claimed_at is not None:
        fields.append("claimed_at=?")
        values.append(claimed_at)
    elif clear_claimed_at:
        fields.append("claimed_at=NULL")
    if not fields:
        return False
    fields.append("updated_at=CURRENT_TIMESTAMP")
    values.append(job_id)
    with get_conn() as conn:
        cursor = conn.execute(
            f"UPDATE jobs SET {', '.join(fields)} WHERE id=?",
            values,
        )
        return cursor.rowcount > 0


def save_checkpoint(job_id, step_name, step_status, output_snapshot=None):
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO job_checkpoints(job_id, step_name, step_status, output_snapshot)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, step_name, step_status, output_snapshot),
        )
        return cursor.lastrowid


def get_latest_checkpoint(job_id):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, job_id, step_name, step_status, output_snapshot, created_at
            FROM job_checkpoints
            WHERE job_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    keys = ("id", "job_id", "step_name", "step_status", "output_snapshot", "created_at")
    return dict(zip(keys, row))


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
