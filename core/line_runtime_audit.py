"""Google Sheets audit for one LINE runtime execution."""
from __future__ import annotations

from core.google_sheets_writer import GoogleSheetsWriter
from core.management_bridge import specialist_roles_for_message

def record_line_runtime(*, user_message: str, reply: str, status: str, route: str) -> None:
    """Best-effort runtime audit; never blocks the LINE response."""
    try:
        writer = GoogleSheetsWriter.from_environment()
        if writer is None:
            print("[GOOGLE-SHEETS] LINE runtime audit skipped: configuration incomplete", flush=True)
            return
        roles = ", ".join(sorted(role.value for role in specialist_roles_for_message(user_message))) or "legacy/unspecified"
        detail = f"channel=line; route={route}; roles={roles}; reply={reply}"
        writer.append_development_result(
            instruction=user_message, status=status, target_path=None,
            branch="line-runtime", detail=detail, base_sha=None, produced_sha=None,
        )
        print("[GOOGLE-SHEETS] LINE runtime audit appended", flush=True)
    except Exception as exc:
        print(f"[GOOGLE-SHEETS] LINE runtime audit failed (non-blocking): {type(exc).__name__}: {exc}", flush=True)
