"""E2E (LINE -> line-bot -> n8n -> /internal/ask -> AI/MCP -> /internal/push -> LINE)
処理経路の「どこで止まっているか」を可視化するための記録レイヤー。

設計方針:
- 既存のDB(db.py)のテーブル・関数には一切手を入れず、別テーブル(e2e_steps)を
  同じSQLiteファイル内に追加する(get_conn()を再利用するのみ)。
- 各ステップの「直近の状態」だけを1行ずつ保持するシンプルな設計。
  (メッセージ単位でのトレースIDによる厳密な相関はスコープ外。
   n8nワークフロー側の変更なしに実現するため、タイムアウト方式で
   「My workflow」等、直接観測できないステップの状態を推定する)
- record_step() は例外を外に投げない(監視機能の障害で本体の処理を
  巻き込んで落とさないため)。
"""

import time
from datetime import datetime, timezone

from db import get_conn

# 表示順(E2E経路の順序)
STEP_ORDER = [
    "line_in",         # LINE -> line-bot (Webhook受信)
    "line_bot",        # line-bot自体の処理(受信〜n8nへの委譲判断)
    "n8n_webhook",     # n8n Webhookへの送信
    "n8n_workflow",    # n8n内のワークフロー実行(直接観測不可・推定)
    "internal_ask",    # /internal/ask
    "ai_mcp",          # AI / MCP呼び出し(internal_ask内部)
    "internal_push",   # /internal/push
    "line_out",        # LINEへの最終送信(reply/push)
]

STEP_LABELS = {
    "line_in": "LINE",
    "line_bot": "line-bot",
    "n8n_webhook": "n8n Webhook",
    "n8n_workflow": "My workflow",
    "internal_ask": "/internal/ask",
    "ai_mcp": "AI / MCP",
    "internal_push": "/internal/push",
    "line_out": "LINE",
}

# このステップが更新されないまま何秒経過したら「止まっている」とみなすか
STEP_TIMEOUT_SEC = 90

# 直接観測できず、前後のステップから推定するステップ
INFERRED_STEPS = {"n8n_workflow"}


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


def init_e2e_table():
    """e2e_steps テーブルを作成する(存在しなければ)。init_db()とは独立して
    呼べるようにしておき、既存のinit_db()の中身には変更を加えない。"""
    try:
        with get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS e2e_steps(
                    step_key TEXT PRIMARY KEY,
                    status TEXT,                  -- 'ok' | 'error'
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


def record_step(step_key, success, http_status=None, response_time_ms=None,
                 error=None, error_location=None):
    """1ステップの結果を記録する。監視用なので失敗しても例外を投げない。"""
    if step_key not in STEP_ORDER:
        print(f"[E2E] unknown step_key: {step_key}")
        return

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
            else:
                if success:
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
                            status, now, http_status, response_time_ms,
                            error, error_location, now, step_key,
                        ),
                    )

            conn.execute(
                """
                INSERT INTO e2e_log(
                    step_key, status, http_status, response_time_ms,
                    error, error_location
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (step_key, status, http_status, response_time_ms, error, error_location),
            )
    except Exception as e:
        print("[E2E] record_step error:", e)


class StepTimer:
    """with文で計測し、成功/失敗を自動でrecord_stepするヘルパー。

    with StepTimer("internal_ask") as t:
        ... 処理 ...
        t.ok(http_status=200)
    失敗時は t.fail(error=str(e), error_location="generate_reply") を呼ぶか、
    withブロック内で例外が出ればそれを自動的にfail扱いにする。
    """

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
            self.step_key, True,
            http_status=http_status,
            response_time_ms=self._elapsed_ms(),
        )

    def fail(self, http_status=None, error=None, error_location=None):
        if self._done:
            return
        self._done = True
        record_step(
            self.step_key, False,
            http_status=http_status,
            response_time_ms=self._elapsed_ms(),
            error=(str(error) if error is not None else None),
            error_location=error_location,
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self._done and exc_type is not None:
            self.fail(error=exc_val, error_location=self.step_key)
        # 例外はここで飲み込まず、呼び出し元に伝播させる
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

    result = {}
    for r in rows:
        result[r[0]] = {
            "status": r[1],
            "last_success_at": r[2],
            "last_failure_at": r[3],
            "last_http_status": r[4],
            "last_response_time_ms": r[5],
            "last_error": r[6],
            "last_error_location": r[7],
            "updated_at": r[8],
        }
    return result


def _parse_ts(ts):
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return datetime.strptime(ts, fmt)
        except Exception:
            pass
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def get_e2e_status():
    """E2E経路の各ステップの現在状態を、上から順に評価して返す。

    ルール:
    - 直近のサイクルは line_in の最終更新時刻を起点とする。
    - 各ステップについて、起点以降に更新されていれば その ok/error を採用。
    - 起点以降まだ更新されていない場合:
        - 直前のステップが既にNOT_REACHED/ERRORならこのステップもNOT_REACHED。
        - 直前のステップがOKで、STEP_TIMEOUT_SECを超えて無応答ならこのステップを
          STOP(タイムアウト推定エラー)とし、以降をNOT_REACHEDにする。
        - タイムアウト未経過なら「処理中」としてNOT_REACHED(⚪)扱いにする
          (誤ってエラー表示にしないための保険)。
    - n8n_workflow は直接観測できないため、n8n_webhookの成功時刻と
      internal_askの直近実行時刻の前後関係から推定する。
    """
    steps = _get_all_steps()
    now = _now()

    line_in = steps.get("line_in")
    cycle_start = _parse_ts(line_in["updated_at"]) if line_in else None

    results = []
    stopped = False
    prev_ok_at = cycle_start

    for step_key in STEP_ORDER:
        label = STEP_LABELS[step_key]

        if cycle_start is None:
            results.append({
                "key": step_key, "label": label, "state": "unknown",
                "detail": None,
            })
            continue

        if stopped:
            results.append({
                "key": step_key, "label": label, "state": "not_reached",
                "detail": steps.get(step_key),
            })
            continue

        row = steps.get(step_key)

        if step_key == "n8n_workflow":
            # n8n_webhook成功後、internal_askが動いていれば workflow は
            # 実行されたとみなす(推定)。internal_askがまだ/更新されていない
            # 場合はタイムアウト判定に委ねる。
            internal_ask_row = steps.get("internal_ask")
            ask_updated = _parse_ts(internal_ask_row["updated_at"]) if internal_ask_row else None
            if ask_updated and prev_ok_at and ask_updated >= prev_ok_at:
                results.append({
                    "key": step_key, "label": label, "state": "ok",
                    "detail": {"inferred": True},
                })
                prev_ok_at = ask_updated
                continue
            # まだ内部askに到達していない → タイムアウト判定へフォールスルー
            row = None

        if step_key == "ai_mcp" and row and row["status"] == "ok":
            # ai_mcpはinternal_ask内部の入れ子StepTimerであり、
            # ai_timer.ok()がinternal_ask自身のok()より先に呼ばれるため、
            # 直前ステップ(internal_ask)のupdated_atより数ms早い記録になる
            # のが正常な順序。prev_ok_atではなくcycle_start以降の成功記録
            # であればOKとする。
            ai_updated = _parse_ts(row["updated_at"])
            if ai_updated and cycle_start and ai_updated >= cycle_start:
                results.append({"key": step_key, "label": label, "state": "ok", "detail": row})
                continue

        row_updated = _parse_ts(row["updated_at"]) if row else None

        if row_updated and prev_ok_at and row_updated >= prev_ok_at:
            if row["status"] == "ok":
                results.append({"key": step_key, "label": label, "state": "ok", "detail": row})
                prev_ok_at = row_updated
            else:
                results.append({"key": step_key, "label": label, "state": "error", "detail": row})
                stopped = True
        else:
            # このサイクルではまだ更新されていない
            elapsed = (now - prev_ok_at).total_seconds() if prev_ok_at else None
            if elapsed is not None and elapsed > STEP_TIMEOUT_SEC:
                results.append({
                    "key": step_key, "label": label, "state": "stop_timeout",
                    "detail": row,
                })
                stopped = True
            else:
                results.append({
                    "key": step_key, "label": label, "state": "not_reached",
                    "detail": row,
                })
                stopped = True  # まだ来ていない = これ以降も未到達として表示

    overall_error = any(s["state"] in ("error", "stop_timeout") for s in results)
    overall_unknown = cycle_start is None

    if overall_unknown:
        overall = "unknown"
    elif overall_error:
        overall = "error"
    elif all(s["state"] == "ok" for s in results):
        overall = "ok"
    else:
        overall = "unknown"

    return {
        "overall": overall,
        "cycle_start": _iso(cycle_start),
        "steps": [
            {
                "key": s["key"],
                "label": s["label"],
                "state": s["state"],
                "last_success_at": _iso(s["detail"]["last_success_at"]) if s.get("detail") and isinstance(s["detail"], dict) and "last_success_at" in s["detail"] else None,
                "last_failure_at": _iso(s["detail"]["last_failure_at"]) if s.get("detail") and isinstance(s["detail"], dict) and "last_failure_at" in s["detail"] else None,
                "last_http_status": s["detail"].get("last_http_status") if s.get("detail") and isinstance(s["detail"], dict) else None,
                "last_response_time_ms": s["detail"].get("last_response_time_ms") if s.get("detail") and isinstance(s["detail"], dict) else None,
                "last_error": s["detail"].get("last_error") if s.get("detail") and isinstance(s["detail"], dict) else None,
                "last_error_location": s["detail"].get("last_error_location") if s.get("detail") and isinstance(s["detail"], dict) else None,
            }
            for s in results
        ],
    }


def get_last_success():
    steps = _get_all_steps()
    line_out = steps.get("line_out")
    if line_out and line_out.get("last_success_at"):
        return _iso(line_out["last_success_at"])
    return None


def get_last_failure():
    """全ステップの中で最も新しい失敗を返す。"""
    steps = _get_all_steps()
    latest_key, latest_ts = None, None
    for key, row in steps.items():
        ts = _parse_ts(row.get("last_failure_at"))
        if ts and (latest_ts is None or ts > latest_ts):
            latest_ts, latest_key = ts, key
    if not latest_key:
        return None
    row = steps[latest_key]
    return {
        "step": STEP_LABELS.get(latest_key, latest_key),
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
            "step": STEP_LABELS.get(r[0], r[0]),
            "status": r[1],
            "http_status": r[2],
            "response_time_ms": r[3],
            "error": r[4],
            "error_location": r[5],
            "created_at": _iso(r[6]),
        }
        for r in rows
    ]
