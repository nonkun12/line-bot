import os
import unittest
from unittest.mock import Mock, patch

from cloudflare_task_intake import extract_intake_request, submit_line_task


class CloudflareLineIntakeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "CLOUDFLARE_TASK_INTAKE_ENABLED": "true",
            "CLOUDFLARE_TASK_INTAKE_LINE_USER_IDS": "U-authorized",
            "CLOUDFLARE_TASK_API_URL": "https://orca-test-api.norimitsu50.workers.dev",
            "CLOUDFLARE_TASK_API_TOKEN": "test-secret-not-real",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_only_explicit_prefixes_are_routed(self):
        self.assertEqual(extract_intake_request("D1登録: 分散Loopを監査"), "分散Loopを監査")
        self.assertEqual(extract_intake_request("タスク登録: テスト"), "テスト")
        self.assertEqual(extract_intake_request("Cloudflare登録: 確認"), "確認")
        self.assertIsNone(extract_intake_request("分散Loopを回して"))

    @patch("cloudflare_task_intake.httpx.post")
    def test_disabled_is_fail_closed(self, post):
        os.environ["CLOUDFLARE_TASK_INTAKE_ENABLED"] = "false"
        result = submit_line_task(
            message_id="message-1", user_id="U-authorized", request_text="test"
        )
        self.assertEqual(result["error"], "disabled")
        post.assert_not_called()

    @patch("cloudflare_task_intake.httpx.post")
    def test_user_allowlist_is_required(self, post):
        result = submit_line_task(
            message_id="message-1", user_id="U-other", request_text="test"
        )
        self.assertEqual(result["error"], "not_allowed")
        post.assert_not_called()

    @patch("cloudflare_task_intake.httpx.post")
    def test_success_uses_stable_task_and_event_ids(self, post):
        response = Mock()
        response.status_code = 201
        response.json.return_value = {
            "created": True,
            "duplicate": False,
            "task": {"task_id": "line-" + __import__("hashlib").sha256(
                b"message-1"
            ).hexdigest()[:40]},
        }
        post.return_value = response

        result = submit_line_task(
            message_id="message-1", user_id="U-authorized", request_text="  test  "
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["duplicate"])
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://orca-test-api.norimitsu50.workers.dev/tasks")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-secret-not-real")
        self.assertEqual(kwargs["json"]["source_event_id"], "message-1")
        self.assertEqual(kwargs["json"]["request_text"], "test")

    @patch("cloudflare_task_intake.httpx.post")
    def test_duplicate_response_is_reported(self, post):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "created": False,
            "duplicate": True,
            "task": {"task_id": "line-" + __import__("hashlib").sha256(
                b"message-2"
            ).hexdigest()[:40]},
        }
        post.return_value = response

        result = submit_line_task(
            message_id="message-2", user_id="U-authorized", request_text="test"
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["duplicate"])

    @patch("cloudflare_task_intake.httpx.post")
    def test_http_conflict_is_rejected_without_retry(self, post):
        response = Mock()
        response.status_code = 409
        post.return_value = response

        result = submit_line_task(
            message_id="message-3", user_id="U-authorized", request_text="test"
        )
        self.assertEqual(result["error"], "api_rejected")
        post.assert_called_once()

    @patch("cloudflare_task_intake.httpx.post")
    def test_invalid_request_never_calls_api(self, post):
        result = submit_line_task(
            message_id="message-4", user_id="U-authorized", request_text=" "
        )
        self.assertEqual(result["error"], "invalid_request")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
