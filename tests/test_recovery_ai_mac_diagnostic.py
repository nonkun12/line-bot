"""Safety tests for the read-only Mac Recovery AI diagnostic entrypoint."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.recovery_ai import RecoveryStore
from scripts.recovery_ai_mac_diagnostic import diagnose_existing_incident


class ReadOnlyMacDiagnosticTests(unittest.TestCase):
    def test_existing_repairable_incident_gets_advisory_without_state_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "state.json")
            store.record_failure("task-1", "test_regression", ["tests/test_x.py"])
            before = store.task_status("task-1")
            advisor = Mock(return_value={
                "diagnosis": "原因候補", "action": "ログを調査", "risk": "変更しない"
            })
            result = diagnose_existing_incident(store, "task-1", advisor=advisor)
            self.assertEqual(result["status"], "ADVISORY_ONLY")
            self.assertFalse(result["state_mutated"])
            self.assertEqual(store.task_status("task-1"), before)
            advisor.assert_called_once()

    def test_missing_incident_does_not_call_advisor_or_create_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "state.json")
            result = diagnose_existing_incident(store, "task-1", advisor=Mock())
            self.assertEqual(result["reason"], "no_existing_incident")
            self.assertFalse(store.path.exists())

    def test_held_incident_never_calls_advisor(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "state.json")
            store.record_failure("task-1", "test_regression")
            store.record_failure("task-1", "test_regression")
            store.record_failure("task-1", "test_regression")
            advisor = Mock()
            result = diagnose_existing_incident(store, "task-1", advisor=advisor)
            self.assertEqual(result["status"], "SKIPPED")
            advisor.assert_not_called()

    def test_non_allowlisted_category_never_calls_advisor(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "state.json")
            store.record_failure("task-1", "security_violation")
            advisor = Mock()
            result = diagnose_existing_incident(store, "task-1", advisor=advisor)
            self.assertEqual(result["status"], "SKIPPED")
            advisor.assert_not_called()

    def test_second_same_fingerprint_attempt_does_not_call_advisor(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "state.json")
            store.record_failure("task-1", "test_regression")
            store.record_failure("task-1", "test_regression")
            advisor = Mock()
            result = diagnose_existing_incident(store, "task-1", advisor=advisor)
            self.assertEqual(result["reason"], "incident_held_or_failure_limit")
            self.assertEqual(result["status"], "SKIPPED")
            advisor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
