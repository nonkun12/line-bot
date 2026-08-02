"""
Phase1: 承認状態判定モジュール。

責務:
- ユーザーの承認状態（pending / expired / none）を判定する
- 承認関連のDBアクセスをこのファイルに集約する
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from db import get_conn


class PendingStatus(str, Enum):
    PENDING = "pending"
    EXPIRED = "expired"
    NONE = "none"


@dataclass
class ApprovalRecord:
    user_id: str
    requested_at: str
    expires_at: str
    approved: bool = False
    rejected: bool = False


def _fetch_latest_approval_record(
    user_id: str
) -> Optional[ApprovalRecord]:

    print(
        f"[LOG] _fetch_latest_approval_record called: user_id={user_id}"
    )

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT user_id, requested_at, expires_at, approved, rejected
            FROM approvals
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

    if row is None:
        return None

    return ApprovalRecord(
        user_id=row[0],
        requested_at=row[1],
        expires_at=row[2],
        approved=bool(row[3]),
        rejected=bool(row[4]),
    )


def _parse_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt


def _is_expired(
    record: ApprovalRecord,
    now: Optional[datetime] = None
) -> bool:

    now = now or datetime.now(timezone.utc)

    return _parse_datetime(
        record.expires_at
    ) <= now


def _is_awaiting_approval(
    record: ApprovalRecord
) -> bool:

    return (
        not record.approved
        and not record.rejected
    )


def get_pending_status(
    user_id: str,
    now: Optional[datetime] = None
) -> PendingStatus:

    print(
        f"[LOG] get_pending_status called: user_id={user_id}"
    )

    try:
        record = _fetch_latest_approval_record(
            user_id
        )

    except Exception as e:
        print(
            "DB GET_PENDING_STATUS ERROR:",
            e
        )

        # DBエラー時は安全側
        return PendingStatus.PENDING


    if record is None:
        return PendingStatus.NONE


    if not _is_awaiting_approval(record):
        return PendingStatus.NONE


    if _is_expired(record, now=now):
        return PendingStatus.EXPIRED


    return PendingStatus.PENDING
