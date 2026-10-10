import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("CHAT_DB_PATH", os.path.join(BASE_DIR, "chat.db"))


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
            source TEXT NOT NULL DEFAULT 'line',
            parent_job_id INTEGER,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            last_error TEXT,
            result TEXT,
            claim_token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(parent_job_id) REFERENCES jobs(id)
        )
        """)
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if "claim_token" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN claim_token TEXT")
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at
        ON jobs(status, created_at)
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_type_status_created_at
        ON jobs(job_type, status, created_at)
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_user_id
        ON jobs(user_id)
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_parent_job_id
        ON jobs(parent_job_id)
        """)
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


def create_job(user_id, message, job_type="ai_task", source="line", parent_job_id=None, max_retries=3):
    """非同期実行用Jobをpending状態で登録する。"""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO jobs(user_id, job_type, source, parent_job_id, message, status, max_retries)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (user_id, job_type, source, parent_job_id, message, max_retries),
        )
        return cursor.lastrowid


def get_job(job_id):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, user_id, job_type, source, parent_job_id, message, status,
                   retry_count, max_retries, last_error, result, claim_token,
                   created_at, updated_at
            FROM jobs WHERE id=?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    keys = (
        "id", "user_id", "job_type", "source", "parent_job_id", "message", "status",
        "retry_count", "max_retries", "last_error", "result", "claim_token",
        "created_at", "updated_at"
    )
    return dict(zip(keys, row))


def has_pending_job_by_type(job_type: str) -> bool:
    """Return whether a pending Obsidian job exists without claiming it."""
    if not isinstance(job_type, str) or not job_type.strip():
        raise ValueError("job_type is required")
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM jobs
            WHERE job_type=? AND status='pending'
            ORDER BY id
            LIMIT 1
            """,
            (job_type.strip(),),
        ).fetchone()
    return row is not None


def claim_pending_job():
    """最古のpending Jobを1件だけrunningへ移す。SQLite向けの最小claim実装。"""
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
            SET status='running', updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='pending'
            """,
            (job_id,),
        )
        if cursor.rowcount != 1:
            return None
    return get_job(job_id)


def claim_pending_job_by_type(job_type, *, stale_after_seconds=900):
    """Atomically claim one bounded job of a specific type with a private token."""
    if not isinstance(job_type, str) or not job_type.strip():
        raise ValueError("job_type is required")
    if (
        not isinstance(stale_after_seconds, int)
        or isinstance(stale_after_seconds, bool)
        or stale_after_seconds < 60
        or stale_after_seconds > 3600
    ):
        raise ValueError("stale_after_seconds must be between 60 and 3600")

    token = secrets.token_urlsafe(32)
    stale_expr = f"-{stale_after_seconds} seconds"

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status='pending',
                claim_token=NULL,
                retry_count=retry_count + 1,
                updated_at=CURRENT_TIMESTAMP
            WHERE job_type=?
              AND status='running'
              AND updated_at < datetime('now', ?)
              AND retry_count < max_retries
            """,
            (job_type.strip(), stale_expr),
        )
        row = conn.execute(
            """
            SELECT id
            FROM jobs
            WHERE job_type=? AND status='pending'
            ORDER BY id
            LIMIT 1
            """,
            (job_type.strip(),),
        ).fetchone()
        if row is None:
            return None
        job_id = row[0]
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status='running',
                claim_token=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND job_type=? AND status='pending'
            """,
            (token, job_id, job_type.strip()),
        )
        if cursor.rowcount != 1:
            return None
    return get_job(job_id)


def complete_claimed_job(
    job_id,
    claim_token,
    *,
    success,
    result=None,
    last_error=None,
):
    """Complete only the exact running job claimed by this bridge instance."""
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise ValueError("job_id is required")
    if not isinstance(claim_token, str) or not claim_token.strip():
        raise ValueError("claim_token is required")
    if not isinstance(success, bool):
        raise ValueError("success must be boolean")
    status = "completed" if success else "failed"
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status=?,
                result=?,
                last_error=?,
                claim_token=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='running' AND claim_token=?
            """,
            (
                status,
                result,
                last_error,
                job_id,
                claim_token,
            ),
        )
        return cursor.rowcount == 1



_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_JOB_ID = 2**31 - 1
_OPERATOR_CANCEL_ERROR = "cancelled by operator"


def _message_sha256(message):
    if not isinstance(message, str):
        return None
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def _is_valid_job_id(job_id):
    return (
        isinstance(job_id, int)
        and not isinstance(job_id, bool)
        and 0 < job_id <= _MAX_JOB_ID
    )


def _readonly_conn():
    """Open the jobs DB so that the SQLite engine itself rejects every write."""
    uri = Path(DB).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def get_job_status_summary(job_id, job_type):
    """Read-only status of exactly one job of the given type."""
    if not isinstance(job_type, str) or not job_type.strip():
        raise ValueError("job_type is required")
    if not _is_valid_job_id(job_id):
        return None
    with closing(_readonly_conn()) as conn:
        row = conn.execute(
            """
            SELECT id, job_type, status, retry_count, max_retries, message,
                   claim_token IS NOT NULL, last_error IS NOT NULL,
                   created_at, updated_at
            FROM jobs
            WHERE id=? AND job_type=?
            """,
            (job_id, job_type.strip()),
        ).fetchone()
    if row is None:
        return None
    message = row[5]
    return {
        "id": row[0],
        "job_type": row[1],
        "status": row[2],
        "retry_count": row[3],
        "max_retries": row[4],
        "message_sha256": _message_sha256(message),
        "message_chars": len(message) if isinstance(message, str) else 0,
        "has_claim": bool(row[6]),
        "has_error": bool(row[7]),
        "created_at": row[8],
        "updated_at": row[9],
    }


def cancel_pending_job_by_type(job_id, job_type, expected_message_sha256):
    """Atomically cancel one exactly identified pending job and audit its prior state."""
    if not _is_valid_job_id(job_id):
        raise ValueError("job_id is invalid")
    if not isinstance(job_type, str) or not job_type.strip():
        raise ValueError("job_type is required")
    if not isinstance(expected_message_sha256, str) or not _SHA256_HEX_RE.fullmatch(
        expected_message_sha256
    ):
        raise ValueError("expected_message_sha256 must be 64 lowercase hex characters")
    job_type = job_type.strip()

    conn = get_conn()
    try:
        conn.create_function("_sha256_hex", 1, _message_sha256, deterministic=True)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT job_type, status, message, retry_count, max_retries, updated_at,
                   claim_token
            FROM jobs WHERE id=?
            """,
            (job_id,),
        ).fetchone()
        if row is None or row[0] != job_type:
            conn.rollback()
            return {"outcome": "not_found", "status": None}

        message_hash = _message_sha256(row[2])
        if message_hash is None or not hmac.compare_digest(
            message_hash, expected_message_sha256
        ):
            conn.rollback()
            return {"outcome": "message_mismatch", "status": None}
        if row[1] != "pending":
            conn.rollback()
            return {"outcome": "not_pending", "status": row[1]}
        if row[6] is not None:
            conn.rollback()
            return {"outcome": "not_cancellable", "status": "pending"}

        cursor = conn.execute(
            """
            UPDATE jobs
            SET status='failed', last_error=?, claim_token=NULL, updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND job_type=? AND status='pending'
              AND claim_token IS NULL AND _sha256_hex(message)=?
            """,
            (_OPERATOR_CANCEL_ERROR, job_id, job_type, expected_message_sha256),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return {"outcome": "not_cancellable", "status": row[1]}

        conn.execute(
            """
            INSERT INTO job_checkpoints(job_id, step_name, step_status, output_snapshot)
            VALUES (?, ?, ?, ?)
            """,
            (
                job_id,
                "operator_cancel",
                "cancelled",
                json.dumps(
                    {
                        "previous_status": "pending",
                        "previous_retry_count": row[3],
                        "previous_max_retries": row[4],
                        "previous_updated_at": row[5],
                        "message_sha256": message_hash,
                    },
                    sort_keys=True,
                ),
            ),
        )
        conn.commit()
        return {"outcome": "cancelled", "status": "failed"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def backup_database(dest_path):
    """Create an exclusive, owner-only consistent backup without overwriting anything."""
    dest = Path(dest_path).resolve()
    if not dest.parent.is_dir():
        raise FileNotFoundError("backup destination directory does not exist")

    # O_EXCL prevents overwriting an existing file or following a symlink.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(str(dest), flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        created_stat = os.fstat(fd)
    except Exception:
        os.close(fd)
        try:
            dest.unlink()
        except OSError:
            pass
        raise
    os.close(fd)

    try:
        # mode=rw requires the exclusively-created file to still exist.
        target_uri = dest.as_uri() + "?mode=rw"
        with closing(_readonly_conn()) as source, closing(
            sqlite3.connect(target_uri, uri=True)
        ) as target:
            source.backup(target)
        return str(dest)
    except Exception:
        # Remove only the file we created; never unlink a replacement.
        try:
            current_stat = dest.stat()
            if (current_stat.st_dev, current_stat.st_ino) == (
                created_stat.st_dev, created_stat.st_ino
            ):
                dest.unlink()
        except OSError:
            pass
        raise


def update_job(job_id, status=None, result=None, last_error=None, retry_count=None):
    """Job状態を部分更新する。指定された値だけを更新する。"""
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
            (job_id,)
        ).fetchone()
    if row is None:
        return None
    keys = ("id", "job_id", "step_name", "step_status", "output_snapshot", "created_at")
    return dict(zip(keys, row))


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
