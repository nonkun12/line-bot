"""Unit tests for the safe, optional local fm advisor."""
import json
import unittest
from unittest.mock import patch

from scripts import recovery_ai_fm_advisor as advisor


class AdvisorValidationTests(unittest.TestCase):
    def test_accepts_exact_schema(self):
        result = advisor._validate_response(
            '{"diagnosis":"原因候補","action":"テストを確認","risk":"変更は禁止"}'
        )
        self.assertEqual(result["diagnosis"], "原因候補")
        self.assertEqual(set(result), {"diagnosis", "action", "risk"})

    def test_rejects_non_json(self):
        with self.assertRaises(advisor.AdvisorError):
            advisor._validate_response("not json")

    def test_rejects_missing_or_extra_keys(self):
        for raw in (
            '{"diagnosis":"a","action":"b"}',
            '{"diagnosis":"a","action":"b","risk":"c","command":"rm -rf"}',
        ):
            with self.subTest(raw=raw), self.assertRaises(advisor.AdvisorError):
                advisor._validate_response(raw)

    def test_rejects_non_string_or_empty_values(self):
        with self.assertRaises(advisor.AdvisorError):
            advisor._validate_response(
                json.dumps({"diagnosis": "ok", "action": "", "risk": "ok"})
            )

    def test_non_macos_fails_closed(self):
        with patch.object(advisor.platform, "system", return_value="Linux"):
            with self.assertRaisesRegex(advisor.AdvisorError, "requires macOS"):
                advisor.diagnose("task-1", "timeout")

    def test_custom_executable_is_not_supported(self):
        # The adapter's executable is intentionally fixed to the local `fm` CLI.
        with self.assertRaises(TypeError):
            advisor.diagnose("task-1", "timeout", executable="/bin/echo")

    @patch.object(advisor.platform, "system", return_value="Darwin")
    @patch.object(advisor.shutil, "which", return_value="/usr/bin/fm")
    @patch.object(advisor.subprocess, "run")
    def test_runs_fm_without_shell_and_returns_validated_json(
        self, run_mock, which_mock, _platform_mock
    ):
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = (
            '{"diagnosis":"原因候補","action":"テスト確認","risk":"変更しない"}'
        )
        result = advisor.diagnose(
            "task-1", "test_regression", ["tests/test_example.py::test_case"]
        )
        self.assertEqual(result["risk"], "変更しない")
        args, kwargs = run_mock.call_args
        self.assertEqual(args[0][0], "/usr/bin/fm")
        self.assertNotIn("shell", kwargs)
        self.assertIn("--no-stream", args[0])
        self.assertIn("task-1", kwargs["input"])
        which_mock.assert_called_once_with("fm")

    @patch.object(advisor.platform, "system", return_value="Darwin")
    @patch.object(advisor.shutil, "which", return_value="/usr/bin/fm")
    @patch.object(advisor.subprocess, "run")
    def test_nonzero_exit_does_not_leak_stderr(
        self, run_mock, _which_mock, _platform_mock
    ):
        run_mock.return_value.returncode = 1
        run_mock.return_value.stdout = ""
        run_mock.return_value.stderr = "SECRET_TOKEN=do-not-print"
        with self.assertRaises(advisor.AdvisorError) as caught:
            advisor.diagnose("task-1", "timeout")
        self.assertNotIn("SECRET_TOKEN", str(caught.exception))

    @patch.object(advisor.platform, "system", return_value="Darwin")
    @patch.object(advisor.shutil, "which", return_value="/usr/bin/fm")
    @patch.object(advisor.subprocess, "run")
    def test_timeout_is_bounded_and_reported(
        self, run_mock, _which_mock, _platform_mock
    ):
        from subprocess import TimeoutExpired
        run_mock.side_effect = TimeoutExpired("fm", 3)
        with self.assertRaisesRegex(advisor.AdvisorError, "timed out"):
            advisor.diagnose("task-1", "timeout", timeout_seconds=3)

    def test_rejects_invalid_timeout(self):
        with patch.object(advisor.platform, "system", return_value="Darwin"):
            with self.assertRaises(ValueError):
                advisor.diagnose("task-1", "timeout", timeout_seconds=0)


if __name__ == "__main__":
    unittest.main()
