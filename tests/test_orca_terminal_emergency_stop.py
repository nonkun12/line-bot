import unittest
from unittest.mock import MagicMock, patch

from scripts.orca_emergency_stop import activate_from_terminal


class TerminalEmergencyStopTests(unittest.TestCase):
    @patch("scripts.orca_emergency_stop.activate_emergency_stop")
    @patch("scripts.orca_emergency_stop._store")
    def test_terminal_command_latches_shared_durable_stop(self, store_factory, activate):
        store = MagicMock()
        snapshot = MagicMock()
        store.read.return_value = snapshot
        store_factory.return_value = store
        activate.return_value = {"status": "EMERGENCY_STOPPED"}
        message = activate_from_terminal(reason="operator requested stop")
        self.assertIn("Emergency Stop", message)
        store.read.assert_called_once_with()
        kwargs = activate.call_args.kwargs
        self.assertIs(kwargs["store"], store)
        self.assertIs(kwargs["snapshot"], snapshot)
        self.assertEqual(kwargs["reason"], "operator requested stop")
        self.assertTrue(kwargs["human_authorized"])
        self.assertEqual(kwargs["requested_by"].split(":", 1)[0], "terminal")

    def test_terminal_command_requires_reason(self):
        with self.assertRaisesRegex(ValueError, "stop_reason_required"):
            activate_from_terminal(reason="  ")

    @patch("scripts.orca_emergency_stop.activate_emergency_stop")
    @patch("scripts.orca_emergency_stop._store")
    def test_already_stopped_is_idempotent(self, store_factory, activate):
        store = MagicMock()
        store.read.return_value = MagicMock()
        store_factory.return_value = store
        activate.return_value = {"status": "ALREADY_STOPPED"}
        message = activate_from_terminal(reason="repeat stop")
        self.assertIn("既にEmergency Stop", message)


if __name__ == "__main__":
    unittest.main()
