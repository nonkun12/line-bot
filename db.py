import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("CHAT_DB_PATH", os.path.join(BASE_DIR, "chat.db"))
DEFAULT_JOB_LEASE_SECONDS = int(os.environ.get("JOB_LEASE_SECONDS", "300"))
SQLITE_TIMEOUT_SECONDS = float(os.environ.get("SQLITE_TIMEOUT_SECONDS", "30.0"))
SQLITE_BUSY_TIMEOUT_MS = int(os.environ.get("SQLITE_BUSY_TIMEOUT_MS", "30000"))


def get_conn():
    print("[LOG] get_conn called")
    conn = sqlite3.connect(DB, check_same_thread=False, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout={max(1, SQLITE_BUSY_TIMEOUT_MS)}")
    return conn


def _enable_wal(conn):
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError as exc:
        print("[LOG] SQLite WAL setup skipped:", exc)


def _ensure_job_columns(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "worker_id" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN worker_id TEXT")
    if "lease_until" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN lease_until TIMESTAMP")


def init_db():
    print("[LOG] init_db called")
    with get_conn() as conn:
        _enable_wal(conn)
        conn.execute("""CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS processed_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            user_id TEXT,
            source TEXT DEFAULT 'line',
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_processed_events_event_id ON processed_events(event_id)")
        conn.execute("""CREATE TABLE IF NOT EXISTS approvals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            approved INTEGER DEFAULT 0,
            rejected INTEGER DEFAULT 0
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_user_id ON approvals(user_id)")
        conn.execute("""CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            job_type TEXT NOT NULL DEFAULT 'ai_task',
            source TEXT NOT NULL DEFAULT 'line',
            parent_job_id INTEGER,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            last_error TEXT,
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            worker_id TEXT,
            lease_until TIMESTAMP,
            FOREIGN KEY(parent_job_id) REFERENCES jobs(id)
        )""")
        _ensure_job_columns(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at ON jobs(status, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_parent_job_id ON jobs(parent_job_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_lease_until ON jobs(status, lease_until)")
        conn.execute("""CREATE TABLE IF NOT EXISTS job_checkpoints(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            step_name TEXT NOT NULL,
            step_status TEXT NOT NULL,
            output_snapshot TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_checkpoints_job_id ON job_checkpoints(job_id, id)")


def save_message(user_id, role, content):
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO messages(user_id, role, content) VALUES (?, ?, ?)", (user_id, role, content))
    except Exception as e:
        print("DB SAVE_MESSAGE ERROR:", e)


def load_history(user_id):
    try:
        with get_conn() as conn:
            rows = conn.execute("SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 8", (user_id,)).fetchall()
    except Exception as e:
        print("DB LOAD_HISTORY ERROR:", e)
        return []
    return list(reversed(rows))


def create_job(user_id, message, job_type="ai_task", source="line", parent_job_id=None, max_retries=3):
    with get_conn() as conn:
        _ensure_job_columns(conn)
        cursor = conn.execute(
            "INSERT INTO jobs(user_id, job_type, source, parent_job_id, message, status, max_retries, worker_id, lease_until) VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL, NULL)",
            (user_id, job_type, source, parent_job_id, message, max_retries),
        )
        return cursor.lastrowid


def get_job(job_id):
    with get_conn() as conn:
        _ensure_job_columns(conn)
        row = conn.execute("SELECT id, user_id, job_type, source, parent_job_id, message, status, retry_count, max_retries, last_error, result, created_at, updated_at, worker_id, lease_until FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return None
    keys = ("id", "user_id", "job_type", "source", "parent_job_id", "message", "status", "retry_count", "max_retries", "last_error", "result", "created_at", "updated_at", "worker_id", "lease_until")
    return dict(zip(keys, row))


def claim_pending_job(worker_id=None, lease_seconds=DEFAULT_JOB_LEASE_SECONDS):
    worker_id = str(worker_id or f"pid:{os.getpid()}")
    lease_seconds = max(1, int(lease_seconds))
    with get_conn() as conn:
        _ensure_job_columns(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT id FROM jobs WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            conn.rollback()
            return None
        job_id = row[0]
        cursor = conn.execute("UPDATE jobs SET status='running', worker_id=?, lease_until=datetime('now', ?), updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (worker_id, f"+{lease_seconds} seconds", job_id))
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
    return get_job(job_id)


def renew_job_lease(job_id, worker_id, lease_seconds=DEFAULT_JOB_LEASE_SECONDS):
    worker_id = str(worker_id)
    lease_seconds = max(1, int(lease_seconds))
    with get_conn() as conn:
        cursor = conn.execute("UPDATE jobs SET lease_until=datetime('now', ?), updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='running' AND worker_id=?", (f"+{lease_seconds} seconds", job_id, worker_id))
        return cursor.rowcount == 1


def update_job(job_id, status=None, result=None, last_error=None, retry_count=None, worker_id=None, lease_until=None, clear_lease=False):
    fields, values = [], []
    if status is not None:
        fields.append("status=?"); values.append(status)
    if result is not None:
        fields.append("result=?"); values.append(result)
    if last_error is not None:
        fields.append("last_error=?"); values.append(last_error)
    if retry_count is not None:
        fields.append("retry_count=?"); values.append(retry_count)
    if worker_id is not None:
        fields.append("worker_id=?"); values.append(worker_id)
    if lease_until is not None:
        fields.append("lease_until=?"); values.append(lease_until)
    if clear_lease:
        fields.extend(["worker_id=NULL", "lease_until=NULL"])
    if not fields:
        return False
    fields.append("updated_at=CURRENT_TIMESTAMP")
    values.append(job_id)
    with get_conn() as conn:
        _ensure_job_columns(conn)
        cursor = conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", values)
        return cursor.rowcount > 0


def save_checkpoint(job_id, step_name, step_status, output_snapshot=None):
    with get_conn() as conn:
        cursor = conn.execute("INSERT INTO job_checkpoints(job_id, step_name, step_status, output_snapshot) VALUES (?, ?, ?, ?)", (job_id, step_name, step_status, output_snapshot))
        return cursor.lastrowid


def get_latest_checkpoint(job_id):
    with get_conn() as conn:
        row = conn.execute("SELECT id, job_id, step_name, step_status, output_snapshot, created_at FROM job_checkpoints WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    if row is None:
        return None
    return dict(zip(("id", "job_id", "step_name", "step_status", "output_snapshot", "created_at"), row))


def create_processed_event(event_id, user_id=None, source="line"):
    try:
        with get_conn() as conn:
            cursor = conn.execute("INSERT OR IGNORE INTO processed_events(event_id, user_id, source) VALUES (?, ?, ?)", (event_id, user_id, source))
            return cursor.rowcount > 0
    except Exception as e:
        print("DB CREATE_PROCESSED_EVENT ERROR:", e)
        return False


def get_processed_event(event_id):
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT event_id, user_id, source, processed_at, updated_at FROM processed_events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                return None
            return {"event_id": row[0], "user_id": row[1], "source": row[2], "processed_at": row[3], "updated_at": row[4]}
    except Exception as e:
        print("DB GET_PROCESSED_EVENT ERROR:", e)
        return None


def is_processed_event(event_id):
    return get_processed_event(event_id) is not None


def update_processed_event(event_id, user_id=None, source=None):
    try:
        with get_conn() as conn:
            cursor = conn.execute("UPDATE processed_events SET user_id=COALESCE(?, user_id), source=COALESCE(?, source), updated_at=CURRENT_TIMESTAMP WHERE event_id=?", (user_id, source, event_id))
            return cursor.rowcount > 0
    except Exception as e:
        print("DB UPDATE_PROCESSED_EVENT ERROR:", e)
        return False


def delete_processed_event(event_id):
    try:
        with get_conn() as conn:
            cursor = conn.execute("DELETE FROM processed_events WHERE event_id=?", (event_id,))
            return cursor.rowcount > 0
    except Exception as e:
        print("DB DELETE_PROCESSED_EVENT ERROR:", e)
        return False


def list_processed_events(limit=100):
    try:
        with get_conn() as conn:
            rows = conn.execute("SELECT event_id, user_id, source, processed_at, updated_at FROM processed_events ORDER BY processed_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
            return [{"event_id": r[0], "user_id": r[1], "source": r[2], "processed_at": r[3], "updated_at": r[4]} for r in rows]
    except Exception as e:
        print("DB LIST_PROCESSED_EVENTS ERROR:", e)
        return []
