import hashlib
import hmac
from datetime import datetime, timezone

import pytest

from core.orca_distributed_loop_approval import build_distributed_loop_approval_payload

USER = "U" + "a" * 32
NOW = datetime(2026, 11, 12, 1, 2, 3, tzinfo=timezone.utc)
KEY = "k" * 40


def test_protocol_v2_signature_binds_task_type_and_bound():
    payload = build_distributed_loop_approval_payload(
        "loop-task-1", "分散Loopを4回、安全確認付きで実行",
        USER, 4, KEY, now=NOW,
    )
    canonical = "\n".join((
        "v2", "loop-task-1",
        hashlib.sha256("分散Loopを4回、安全確認付きで実行".encode()).hexdigest(),
        USER, "distributed_loop", "4",
        payload["issued_at"], payload["expires_at"], payload["nonce"],
    ))
    expected = hmac.new(KEY.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    assert payload["signature"] == expected
    assert payload["task_type"] == "distributed_loop"
    assert payload["max_tasks"] == 4
    assert payload["expires_at"] == "2026-11-12T02:02:03Z"


@pytest.mark.parametrize("count", [0, 5, True, "4", None])
def test_rejects_invalid_task_bound(count):
    with pytest.raises(ValueError, match="max_tasks"):
        build_distributed_loop_approval_payload("loop-1", "分散Loop開始", USER, count, KEY, now=NOW)


@pytest.mark.parametrize("user", [None, "", "Uinvalid"])
def test_rejects_invalid_line_owner(user):
    with pytest.raises(ValueError, match="LINE user"):
        build_distributed_loop_approval_payload("loop-1", "分散Loop開始", user, 1, KEY, now=NOW)


def test_rejects_short_hmac_key():
    with pytest.raises(ValueError, match="HMAC secret"):
        build_distributed_loop_approval_payload("loop-1", "分散Loop開始", USER, 1, "short", now=NOW)
