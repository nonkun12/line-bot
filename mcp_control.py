import os
import sqlite3

from db import DB, get_conn

MCP_ON_COMMANDS = {"MCP ON", "MCP ONにして", "MCPをON", "MCPをONにして"}
MCP_OFF_COMMANDS = {"MCP OFF", "MCP OFFにして", "MCPをOFF", "MCPをOFFにして"}
MCP_STATUS_COMMANDS = {"MCP 状態", "MCP状態", "MCP STATUS", "MCPステータス"}

def _ensure_table():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_control(
            id INTEGER PRIMARY KEY CHECK(id=1),
            enabled INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO mcp_control(id, enabled) VALUES (1, 0)"
        )

def is_mcp_enabled():
    _ensure_table()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT enabled FROM mcp_control WHERE id=1"
        ).fetchone()
    return bool(row and row[0])

def set_mcp_enabled(enabled: bool):
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be boolean")
    _ensure_table()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE mcp_control
            SET enabled=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=1
            """,
            (1 if enabled else 0,),
        )
    return enabled

def _allowed_user_ids():
    raw = os.environ.get("MCP_CONTROL_USER_IDS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}

def handle_mcp_control_command(user_id: str, message: str):
    """Return a reply for an explicit MCP control command, otherwise None.

    Control is fail-closed: without an explicit allowlist, ON/OFF cannot be
    changed. This command only changes the local MCP Gate state; it does not
    grant any new tool capability.
    """
    command = str(message or "").strip()
    if command not in MCP_ON_COMMANDS | MCP_OFF_COMMANDS | MCP_STATUS_COMMANDS:
        return None

    if command in MCP_STATUS_COMMANDS:
        return "MCPはONです。" if is_mcp_enabled() else "MCPはOFFです。"

    if str(user_id or "").strip() not in _allowed_user_ids():
        return "MCPのON/OFF権限がありません。"

    enabled = command in MCP_ON_COMMANDS
    set_mcp_enabled(enabled)
    return "MCPをONにしました。" if enabled else "MCPをOFFにしました。"
