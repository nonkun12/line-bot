"""Terminal command for the durable Orca Emergency Stop.

Usage:
  python -m scripts.orca_emergency_stop --reason "manual emergency stop"

This command only latches STOP. It has no clear/reset mode.
"""
from __future__ import annotations

import argparse
import getpass
import uuid
from datetime import datetime, timezone

from core.orca_emergency_stop import _store
from scripts.orca_github_emergency_stop import activate_emergency_stop


def activate_from_terminal(*, reason: str) -> str:
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("stop_reason_required")
    store = _store()
    snapshot = store.read()
    result = activate_emergency_stop(
        store=store,
        snapshot=snapshot,
        requested_by="terminal:" + getpass.getuser(),
        reason=reason.strip(),
        event_id=uuid.uuid4().hex,
        now=datetime.now(timezone.utc),
        human_authorized=True,
    )
    status = result.get("status") if isinstance(result, dict) else None
    if status == "EMERGENCY_STOPPED":
        return "🛑 Orca Emergency Stopを有効化しました。共通の永続STOP状態を記録済みです。自動解除はされません。"
    if status == "ALREADY_STOPPED":
        return "🛑 Orcaは既にEmergency Stop状態です。停止状態を維持しています。"
    raise RuntimeError("emergency_stop_persistence_not_confirmed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Latch Orca Emergency Stop")
    parser.add_argument("--reason", required=True, help="停止理由（監査ログに記録）")
    args = parser.parse_args(argv)
    try:
        print(activate_from_terminal(reason=args.reason))
        return 0
    except Exception as exc:
        print(
            "緊急停止を永続状態へ記録できませんでした。安全のため実行は許可されません。"
            f" 原因: {type(exc).__name__}"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
