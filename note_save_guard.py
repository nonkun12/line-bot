"""Fail-closed, duplicate-safe wrapper around MCP save_note."""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import db
import mcp_client

SAVED_TEXT = "メモを保存しました。"
DUPLICATE_TEXT = "同じ内容のメモが既にあります。"
SAVE_ERROR_PREFIX = "保存エラー"
NO_MATCH_TEXT = "該当するメモはありません。"

SAVED = "saved"
ALREADY_EXISTS = "already_exists"
FAILED = "failed"
UNKNOWN = "unknown"

CallTool = Callable[..., Any]


@dataclass(frozen=True)
class SaveResult:
    status: str
    message: str


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return float(default)


def _write_timeout() -> float:
    return max(1.0, _env_float("MCP_WRITE_TIMEOUT_SEC", 15.0))


def _max_attempts() -> int:
    try:
        return max(1, min(2, int(_env_float("MCP_SAVE_MAX_ATTEMPTS", 2))))
    except ValueError:
        return 2


def _pending_ttl() -> float:
    return max(1.0, _env_float("MCP_SAVE_PENDING_TTL_SEC", 600.0))


def _key(user_id: str, body: str) -> str:
    return hashlib.sha256(f"{user_id}\0{body}".encode("utf-8")).hexdigest()


def _ensure_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS note_save_attempts(
            key TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )


def _claim(key: str) -> Optional[str]:
    now = time.time()
    with db.get_conn() as conn:
        _ensure_table(conn)
        cur = conn.execute(
            "INSERT OR IGNORE INTO note_save_attempts(key,state,updated_at) VALUES (?,?,?)",
            (key, "in_flight", now),
        )
        if cur.rowcount == 1:
            return None
        cur = conn.execute(
            "UPDATE note_save_attempts SET state='in_flight',updated_at=? WHERE key=? AND updated_at<?",
            (now, key, now - _pending_ttl()),
        )
        if cur.rowcount == 1:
            return None
        row = conn.execute("SELECT state FROM note_save_attempts WHERE key=?", (key,)).fetchone()
        return row[0] if row else "in_flight"


def _set_state(key: str, state: str) -> None:
    with db.get_conn() as conn:
        _ensure_table(conn)
        conn.execute(
            "UPDATE note_save_attempts SET state=?,updated_at=? WHERE key=?",
            (state, time.time(), key),
        )


def _release(key: str) -> None:
    with db.get_conn() as conn:
        _ensure_table(conn)
        conn.execute("DELETE FROM note_save_attempts WHERE key=?", (key,))


def _call(call_tool: CallTool, tool: str, args: dict[str, Any], timeout: float):
    try:
        return call_tool(tool, args, timeout=timeout)
    except TypeError:
        return call_tool(tool, args)


def _body_present(call_tool: CallTool, user_id: str, body: str) -> Optional[bool]:
    try:
        text = _call(call_tool, "search_notes", {"user_id": user_id, "keyword": body}, _write_timeout())
    except Exception as exc:
        print(f"[LOG] save_note read-back failed: {type(exc).__name__}", flush=True)
        return None
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if stripped == NO_MATCH_TEXT:
        return False
    if f"内容:{body}\nカテゴリ:" in text:
        return True
    if stripped.startswith("検索エラー"):
        return None
    return False if stripped.startswith("ID:") else None


def _unknown(body: str) -> SaveResult:
    hint = body if len(body) <= 20 else body[:20]
    return SaveResult(
        UNKNOWN,
        "メモの保存結果を確認できませんでした。重複を避けるため自動で再送していません。"
        f"「メモ検索 {hint}」で保存されたか確認してください。",
    )


def save_note_safely(call_tool: CallTool, user_id: str, title: str, body: str, category: str) -> SaveResult:
    """Save once, verify by read-back, and never claim success without evidence."""
    key = _key(user_id, body)
    args = {"user_id": user_id, "title": title, "body": body, "category": category}
    from render_client import mcp_service_session
    try:
        with mcp_service_session():
            blocked = _claim(key)
            if blocked is not None:
                try:
                    mcp_client.wait_for_mcp_http_ready()
                except mcp_client.McpNotReadyError:
                    return _unknown(body)
                present = _body_present(call_tool, user_id, body)
                if present is True:
                    _release(key)
                    return SaveResult(SAVED, "保存済みのメモを確認しました。")
                return _unknown(body)

            try:
                mcp_client.wait_for_mcp_http_ready()
            except mcp_client.McpNotReadyError as exc:
                _release(key)
                print(f"[LOG] save_note not sent: {exc}", flush=True)
                return SaveResult(FAILED, "メモ保存サービスがまだ起動中です。メモは保存していません。1〜2分後にもう一度お試しください。")

            for attempt in range(_max_attempts()):
                try:
                    result = _call(call_tool, "save_note", args, _write_timeout())
                except Exception as exc:
                    verdict = mcp_client.classify_mcp_failure(exc)
                    print(f"[LOG] save_note call failed: {type(exc).__name__} ({verdict})", flush=True)
                    if verdict == "not_delivered" and attempt + 1 < _max_attempts():
                        continue
                    if verdict in ("not_delivered", "rejected"):
                        _release(key)
                        return SaveResult(FAILED, "メモを保存できませんでした。少し時間を置いてもう一度お試しください。")
                    _set_state(key, "unknown")
                    present = _body_present(call_tool, user_id, body)
                    if present is True:
                        _release(key)
                        return SaveResult(SAVED, "メモの保存を確認しました。")
                    return _unknown(body)

                text = result.strip() if isinstance(result, str) else ""
                if text == SAVED_TEXT:
                    present = _body_present(call_tool, user_id, body)
                    if present is True:
                        _release(key)
                        return SaveResult(SAVED, "メモを保存しました。（保存を確認済み）")
                    _set_state(key, "unknown")
                    return _unknown(body)
                if text == DUPLICATE_TEXT:
                    _release(key)
                    return SaveResult(ALREADY_EXISTS, "同じ内容のメモが既に保存されています。（新しくは保存していません）")
                if text.startswith(SAVE_ERROR_PREFIX):
                    present = _body_present(call_tool, user_id, body)
                    if present is True:
                        _release(key)
                        return SaveResult(SAVED, "メモの保存を確認しました。")
                    if present is False:
                        _release(key)
                        return SaveResult(FAILED, "メモを保存できませんでした。少し時間を置いてもう一度お試しください。")
                    _set_state(key, "unknown")
                    return _unknown(body)

                _set_state(key, "unknown")
                present = _body_present(call_tool, user_id, body)
                if present is True:
                    _release(key)
                    return SaveResult(SAVED, "メモの保存を確認しました。")
                return _unknown(body)
    except Exception as exc:
        print(f"[LOG] save_note guard failed closed: {type(exc).__name__}", flush=True)
        return SaveResult(FAILED, "メモを保存できませんでした。少し時間を置いてもう一度お試しください。")
