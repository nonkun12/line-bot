"""Google Sheets audit for one LINE runtime execution."""
from __future__ import annotations

import traceback

from core.google_sheets_writer import GoogleSheetsWriter
from core.management_bridge import specialist_roles_for_message


def record_line_runtime(*, user_message: str, reply: str, status: str, route: str) -> None:
    """Best-effort audit for specialist LINE requests; never blocks the reply.

    Ordinary conversation is intentionally excluded from the Sheets audit.
    Only messages that resolve to at least one registered specialist role are
    operationally meaningful enough to persist.
    """
    try:
        roles = specialist_roles_for_message(user_message)
        if not roles:
            print(
                "[GOOGLE-SHEETS] LINE runtime audit skipped: ordinary conversation",
                flush=True,
            )
            return

        writer = GoogleSheetsWriter.from_environment()
        if writer is None:
            print(
                "[GOOGLE-SHEETS] LINE runtime audit skipped: configuration incomplete",
                flush=True,
            )
            return

        role_names = ", ".join(sorted(role.value for role in roles))
        detail = f"channel=line; route={route}; roles={role_names}; reply={reply}"
        writer.append_development_result(
            instruction=user_message,
            status=status,
            target_path=None,
            branch="line-runtime",
            detail=detail,
            base_sha=None,
            produced_sha=None,
        )
        print("[GOOGLE-SHEETS] LINE runtime audit appended", flush=True)
    except Exception as exc:
        print(
            f"[GOOGLE-SHEETS] LINE runtime audit failed (non-blocking): "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        print("[GOOGLE-SHEETS] LINE runtime audit traceback:", flush=True)
        traceback.print_exc()
