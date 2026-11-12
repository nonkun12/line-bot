from __future__ import annotations

import hashlib
import hmac
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from core.orca_distributed_loop_intake import (
    approve_distributed_loop,
    build_distributed_loop_task_payload,
    register_distributed_loop,
)


USER = "U" + "a" * 32
API = "https://orca.example"
TOKEN = "api-token"
SECRET = "approval-secret-at-least-32-bytes-long"


class DistributedLoopLineRouteTests(unittest.TestCase):
    def test_payload_binds_owner_event_type_and_exact_task_bound(self):
        payload = build_distributed_loop_task_payload(
            task_id="loop-1",
            request_text="分散Loopを3回、安全確認付きで実行",
            source_event_id="line-event-1",
            user_id=USER,
        )
        self.assertEqual(payload, {
            "task_id": "loop-1",
            "task_type": "distributed_loop",
            "request_text": "分散Loopを3回、安全確認付きで実行",
            "max_tasks": 3,
            "source_event_id": "line-event-1",
            "user_id": USER,
        })

    def test_payload_rejects_missing_owner_and_unbounded_or_readonly_commands(self):
        for kwargs in (
            {"task_id": "x", "request_text": "分散Loop開始", "source_event_id": "e", "user_id": None},
            {"task_id": "x", "request_text": "分散Loopを5回、安全確認付きで実行", "source_event_id": "e", "user_id": USER},
            {"task_id": "x", "request_text": "分散Loopの状況", "source_event_id": "e", "user_id": USER},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_distributed_loop_task_payload(**kwargs)

    @patch.dict("os.environ", {"DISTRIBUTED_LOOP_LINE_USER_IDS": USER})
    @patch("core.orca_distributed_loop_intake.httpx.post")
    def test_register_posts_typed_task_and_returns_explicit_approval_instruction(self, post):
        post.return_value = SimpleNamespace(
            status_code=201,
            json=lambda: {"task": {
                "task_id": "line-loop-fixed",
                "task_type": "distributed_loop",
                "max_tasks": 2,
                "status": "queued",
            }},
        )
        with patch("core.orca_distributed_loop_intake.uuid.uuid4") as uuid4:
            uuid4.return_value.hex = "fixed"
            result = register_distributed_loop(
                "分散Loopを2回、安全確認付きで実行", "line-event-2", USER, API, TOKEN,
            )
        self.assertIsNotNone(result)
        reply, retryable = result
        self.assertFalse(retryable)
        self.assertIn("未実行", reply)
        self.assertIn("分散Loop承認:line-loop-fixed", reply)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["task_type"], "distributed_loop")
        self.assertEqual(payload["max_tasks"], 2)
        self.assertEqual(payload["source_event_id"], "line-event-2")
        self.assertEqual(payload["user_id"], USER)

    @patch.dict("os.environ", {"DISTRIBUTED_LOOP_LINE_USER_IDS": ""})
    def test_register_fails_closed_for_non_allowlisted_user(self):
        result = register_distributed_loop("分散Loop開始", "event", USER, API, TOKEN)
        self.assertIn("許可されていません", result[0])

    @patch.dict("os.environ", {"DISTRIBUTED_LOOP_LINE_USER_IDS": USER})
    @patch("core.orca_distributed_loop_intake.httpx.post")
    def test_register_marks_transport_failure_retryable(self, post):
        import httpx
        post.side_effect = httpx.ConnectError("offline")
        result = register_distributed_loop("分散Loop開始", "event", USER, API, TOKEN)
        self.assertTrue(result[1])

    @patch.dict("os.environ", {"DISTRIBUTED_LOOP_LINE_USER_IDS": USER})
    @patch("core.orca_distributed_loop_intake.httpx.post")
    @patch("core.orca_distributed_loop_intake.httpx.get")
    def test_approval_uses_v2_signature_bound_to_task_type_and_max_tasks(self, get, post):
        command = "分散Loopを4回、安全確認付きで実行"
        get.return_value = SimpleNamespace(
            status_code=200,
            json=lambda: {"task": {
                "task_id": "loop-approval",
                "request_text": command,
                "status": "queued",
                "task_type": "distributed_loop",
                "max_tasks": 4,
            }},
        )
        post.return_value = SimpleNamespace(status_code=200, json=lambda: {"approved": True})
        reply, retryable = approve_distributed_loop(
            "分散Loop承認:loop-approval", USER, API, TOKEN, SECRET,
        )
        self.assertFalse(retryable)
        self.assertIn("まだ実行されません", reply)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["task_type"], "distributed_loop")
        self.assertEqual(payload["max_tasks"], 4)
        canonical = "\n".join((
            "v2", "loop-approval", payload["request_hash"], USER,
            "distributed_loop", "4", payload["issued_at"], payload["expires_at"], payload["nonce"],
        ))
        expected = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        self.assertTrue(hmac.compare_digest(payload["signature"], expected))

    @patch.dict("os.environ", {"DISTRIBUTED_LOOP_LINE_USER_IDS": USER})
    @patch("core.orca_distributed_loop_intake.httpx.post")
    @patch("core.orca_distributed_loop_intake.httpx.get")
    def test_approval_rejects_wrong_task_type_without_posting(self, get, post):
        get.return_value = SimpleNamespace(
            status_code=200,
            json=lambda: {"task": {
                "task_id": "app-task",
                "request_text": "アプリ開発: not a loop",
                "status": "queued",
                "task_type": "app_development",
                "max_tasks": 1,
            }},
        )
        reply, _ = approve_distributed_loop(
            "分散Loop承認:app-task", USER, API, TOKEN, SECRET,
        )
        self.assertIn("分散Loopタスクではありません", reply)
        post.assert_not_called()

    def test_unrelated_text_is_not_consumed(self):
        self.assertIsNone(register_distributed_loop("分散Loopの状況を教えて", "event", USER, API, TOKEN))
        self.assertIsNone(approve_distributed_loop("普通の会話", USER, API, TOKEN, SECRET))


if __name__ == "__main__":
    unittest.main()
