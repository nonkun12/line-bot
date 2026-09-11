"""E2E status for the primary LINE -> Core -> Agent -> LINE path.

n8n and the legacy internal endpoints are auxiliary observability only; they are
never part of the primary E2E success decision.
"""

import time
from datetime import datetime, timezone

from db import get_conn

STEP_ORDER = [
    "line_in",
    "core",
    "agent",
    "line_out",
]

STEP_LABELS = {
    "line_in": "LINE",
    "core": "Core",
    "agent": "Agent",
    "line_out": "LINE",
}

AUXILIARY_STEP_ORDER = [
    "n8n_webhook",
    "n8n_workflow",
    "internal_ask",
    "ai_mcp",
    "internal_push",
]

AUXILIARY_STEP_LABELS = {
    "n8n_webhook": "n8n Webhook",
    "n8n_workflow": "n8n workflow",
    "internal_ask": "/internal/ask",
    "ai_mcp": "AI / MCP (legacy)",
    "internal_push": "/internal/push",
}

LEGACY_ALIASES = {
    "line_bot": "line_out",
}

ALL_STEP_KEYS = set(STEP_ORDER) | set(AUXILIARY_STEP_ORDER) | set(LEGACY_ALIASES)
STEP_TIMEOUT_SEC = 90


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


def _canonical_step_key(step_key):
    return LEGACY_ALIASES.get(step_key, step_key)


def _label(step_key):
    canonical = _canonical_step_key(step_key)
    return STEP_LABELS.get(canonical) or AUXILIARY_STEP_LABELS.get(canonical, canonical)


def init_e2e_table():
    """Create E2E tables without changing the existing application schema."""
    try:
        with get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS e2e_steps(
                    step_key TEXT PRIMARY KEY,
                    status TEXT,
                    last_success_at TIMESTAMP,
                    last_failure_at TIMESTAMP,
                    last_http_status INTEGER,
                    last_response_time_ms INTEGER,
                    last_error TEXT,
                    last_error_location TEXT,
                    updated_at TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS e2e_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    step_key TEXT,
                    status TEXT,
                    http_status INTEGER,
                    response_time_ms INTEGER,
                    error TEXT,
                    error_location TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_e2e_log_created_at ON e2e_log(created_at)"
            )
    except Exception as e:
        print("[E2E] init_e2e_table error:", e)


def record_step(
    step_key,
    success,
    http_status=None,
    response_time_ms=None,
    error=None,
    error_location=None,
):
    """Record one step. Monitoring failures never break application traffic."""
    if step_key not in ALL_STEP_KEYS:
        print(f"[E2E] unknown step_key: {step_key}")
        return

    step_key = _canonical_step_key(step_key)
    status = "ok" if success else "error"
    now = _now()

    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT step_key FROM e2e_steps WHERE step_key=?", (step_key,)
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO e2e_steps(
                        step_key, status, last_success_at, last_failure_at,
                        last_http_status, last_response_time_ms,
                        last_error, last_error_location, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        step_key,
                        status,
                        now if success else None,
                        now if not success else None,
                        http_status,
                        response_time_ms,
                        error,
                        error_location,
                        now,
                    ),
                )
            elif success:
                conn.execute(
                    """
                    UPDATE e2e_steps
                    SET status=?, last_success_at=?, last_http_status=?,
                        last_response_time_ms=?, updated_at=?
                    WHERE step_key=?
                    """,
                    (status, now, http_status, response_time_ms, now, step_key),
                )
            else:
                conn.execute(
                    """
                    UPDATE e2e_steps
                    SET status=?, last_failure_at=?, last_http_status=?,
                        last_response_time_ms=?, last_error=?,
                        last_error_location=?, updated_at=?
                    WHERE step_key=?
                    """,
                    (
                        status,
                        now,
                        http_status,
                        response_time_ms,
                        str(error) if error is not None else None,
                        error_location,
                        now,
                        step_key,
                    ),
                )

            conn.execute(
                """
                INSERT INTO e2e_log(
                    step_key, status, http_status, response_time_ms,
                    error, error_location
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    step_key,
                    status,
                    http_status,
                    response_time_ms,
                    str(error) if error is not None else None,
                    error_location,
                ),
            )
    except Exception as e:
        print("[E2E] record_step error:", e)


class StepTimer:
    """Measure a step while preserving the original exception semantics."""

    def __init__(self, step_key):
        self.step_key = step_key
        self._start = None
        self._done = False

    def __enter__(self):
        self._start = time.time()
        return self

    def _elapsed_ms(self):
        return int((time.time() - self._start) * 1000)

    def ok(self, http_status=None):
        if self._done:
            return
        self._done = True
        record_step(
            self.step_key,
            True,
            http_status=http_status,
            response_time_ms=self._elapsed_ms(),
        )

    def fail(self, http_status=None, error=None, error_location=None):
        if self._done:
            return
        self._done = True
        record_step(
            self.step_key,
            False,
            http_status=http_status,
            response_time_ms=self._elapsed_ms(),
            error=error,
            error_location=error_location,
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self._done and exc_type is not None:
            self.fail(error=exc_val, error_location=self.step_key)
        return False


def _get_all_steps():
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT step_key, status, last_success_at, last_failure_at,
                       last_http_status, last_response_time_ms,
                       last_error, last_error_location, updated_at
                FROM e2e_steps
                """
            ).fetchall()
    except Exception as e:
        print("[E2E] _get_all_steps error:", e)
        return {}

    return {
        r[0]: {
            "status": r[1],
            "last_success_at": r[2],
            "last_failure_at": r[3],
            "last_http_status": r[4],
            "last_response_time_ms": r[5],
            "last_error": r[6],
            "last_error_location": r[7],
            "updated_at": r[8],
        }
        for r in rows
    }


def _parse_ts(ts):
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _step_payload(step_key, state, row=None):
    row = row or {}
    return {
        "key": step_key,
        "label": _label(step_key),
        "state": state,
        "last_success_at": _iso(row.get("last_success_at")),
        "last_failure_at": _iso(row.get("last_failure_at")),
        "last_http_status": row.get("last_http_status"),
        "last_response_time_ms": row.get("last_response_time_ms"),
        "last_error": row.get("last_error"),
        "last_error_location": row.get("last_error_location"),
    }


def _evaluate_path(step_order, steps, cycle_start):
    results = []
    previous_time = cycle_start
    stopped = False
    now = _now()

    for step_key in step_order:
        row = steps.get(step_key)
        if stopped or cycle_start is None:
            results.append(_step_payload(step_key, "not_reached" if stopped else "unknown", row))
            continue

        updated = _parse_ts(row.get("updated_at")) if row else None
        if updated and updated >= previous_time:
            if row.get("status") == "ok":
                results.append(_step_payload(step_key, "ok", row))
                previous_time = updated
                continue
            results.append(_step_payload(step_key, "error", row))
            stopped = True
            continue

        elapsed = (now - previous_time).total_seconds() if previous_time else None
        state = "stop_timeout" if elapsed is not None and elapsed > STEP_TIMEOUT_SEC else "not_reached"
        results.append(_step_payload(step_key, state, row))
        stopped = True

    return results


def get_e2e_status():
    """Return primary E2E status plus separately reported auxiliary status."""
    steps = _get_all_steps()
    line_in = steps.get("line_in")
    cycle_start = _parse_ts(line_in.get("updated_at")) if line_in else None

    primary_steps = _evaluate_path(STEP_ORDER, steps, cycle_start)
    primary_errors = {"error", "stop_timeout"}
    if cycle_start is None:
        overall = "unknown"
    elif any(step["state"] in primary_errors for step in primary_steps):
        overall = "error"
    elif all(step["state"] == "ok" for step in primary_steps):
        overall = "ok"
    else:
        overall = "unknown"

    auxiliary_steps = [
        _step_payload(key, "ok" if steps.get(key, {}).get("status") == "ok" else "error" if steps.get(key, {}).get("status") == "error" else "unknown", steps.get(key))
        for key in AUXILIARY_STEP_ORDER
    ]

    return {
        "overall": overall,
        "cycle_start": _iso(cycle_start),
        "steps": primary_steps,
        "auxiliary": auxiliary_steps,
    }


def get_last_success():
    steps = _get_all_steps()
    line_out = steps.get("line_out")
    return _iso(line_out.get("last_success_at")) if line_out and line_out.get("last_success_at") else None


def get_last_failure():
    steps = _get_all_steps()
    latest_key, latest_ts = None, None
    for key, row in steps.items():
        ts = _parse_ts(row.get("last_failure_at"))
        if ts and (latest_ts is None or ts > latest_ts):
            latest_ts, latest_key = ts, key
    if latest_key is None:
        return None
    row = steps[latest_key]
    return {
        "step": _label(latest_key),
        "at": _iso(row.get("last_failure_at")),
        "error": row.get("last_error"),
        "error_location": row.get("last_error_location"),
        "http_status": row.get("last_http_status"),
    }


def get_error_log(limit=30):
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT step_key, status, http_status, response_time_ms,
                       error, error_location, created_at
                FROM e2e_log
                WHERE status='error'
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except Exception as e:
        print("[E2E] get_error_log error:", e)
        return []

    return [
        {
            "step": _label(row[0]),
            "status": row[1],
            "http_status": row[2],
            "response_time_ms": row[3],
            "error": row[4],
            "error_location": row[5],
            "created_at": _iso(row[6]),
        }
        for row in rows
    ]
