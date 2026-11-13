import os
import unittest
from unittest.mock import MagicMock, patch

from core.orca_emergency_stop import is_emergency_stop_command, activate_from_line


class LineEmergencyStopTests(unittest.TestCase):
    def test_stop_command_aliases_are_exact_and_case_insensitive(self):
        for value in ("緊急停止", "緊急停止: 暴走", "ORCA STOP", "EMERGENCY STOP"):
            self.assertTrue(is_emergency_stop_command(value))
        for value in ("緊急停止してください", "please stop", "STOP THE BOT"):
            self.assertFalse(is_emergency_stop_command(value))

    @patch.dict(os.environ, {"DEV_ALLOWED_USER_IDS": "U-authorized"})
    @patch("core.orca_emergency_stop.activate_emergency_stop")
    @patch("core.orca_emergency_stop._store")
    def test_authorized_line_user_latches_shared_stop(self, store_factory, activate):
        store = MagicMock()
        snapshot = MagicMock()
        store.read.return_value = snapshot
        store_factory.return_value = store
        activate.return_value = {"status": "EMERGENCY_STOPPED"}
        reply = activate_from_line(user_id="U-authorized", message="緊急停止: 暴走の兆候")
        self.assertIn("Emergency Stop", reply)
        store.read.assert_called_once_with()
        self.assertEqual(activate.call_args.kwargs["reason"], "暴走の兆候")
        self.assertTrue(activate.call_args.kwargs["human_authorized"])

    @patch.dict(os.environ, {"DEV_ALLOWED_USER_IDS": "U-authorized"})
    @patch("core.orca_emergency_stop._store")
    def test_unauthorized_line_user_is_denied_before_state_access(self, store_factory):
        reply = activate_from_line(user_id="U-other", message="緊急停止")
        self.assertIn("拒否", reply)
        store_factory.assert_not_called()

    @patch.dict(os.environ, {"DEV_ALLOWED_USER_IDS": "U-authorized"})
    @patch("core.orca_emergency_stop.activate_emergency_stop")
    @patch("core.orca_emergency_stop._store")
    def test_unknown_store_result_is_not_reported_as_success(self, store_factory, activate):
        store = MagicMock()
        store.read.return_value = MagicMock()
        store_factory.return_value = store
        activate.return_value = {"status": "UNKNOWN"}
        reply = activate_from_line(user_id="U-authorized", message="緊急停止")
        self.assertIn("確認できません", reply)

    @patch.dict(os.environ, {"DEV_ALLOWED_USER_IDS": ""})
    @patch("core.orca_emergency_stop._store")
    def test_missing_allowlist_fails_closed(self, store_factory):
        reply = activate_from_line(user_id="U-authorized", message="緊急停止")
        self.assertIn("拒否", reply)
        store_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
