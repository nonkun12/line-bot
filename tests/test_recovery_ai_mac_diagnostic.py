"""Safety tests for the read-only Mac Recovery AI diagnostic entrypoint."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.recovery_ai import RecoveryStore, RecoveryStateError
from scripts.recovery_ai_mac_diagnostic import (
    diagnose_existing_incident, load_readonly_store,
)


class ReadOnlyMacDiagnosticTests(unittest.TestCase):
    def test_existing_repairable_incident_gets_advisory_without_state_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = RecoveryStore(path)
            store.record_failure("task-1", "test_regression", ["tests/test_x.py"])
            before = path.read_bytes()
            before_record = store.task_status("task-1")
            advisor = Mock(return_value={
                "diagnosis": "原因候補", "action": "ログを調査", "risk": "変更しない"
            })
            result = diagnose_existing_incident(store, "task-1", advisor=advisor)
            self.assertEqual(result["status"], "ADVISORY_ONLY")
            self.assertFalse(result["state_mutated"])
            self.assertEqual(store.task_status("task-1"), before_record)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), hashlib.sha256(before).hexdigest())
            self.assertEqual(result["updated_at"], before_record["updated_at"])
            advisor.assert_called_once()

    def test_durable_envelope_extracts_recovery_ai_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".autonomous-loop-state.json"
            recovery = {"schema_version": 1, "tasks": {}, "checkpoint": None}
            envelope = {"version": 1, "completed": [], "recovery_ai": recovery}
            path.write_text(json.dumps(envelope), encoding="utf-8")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            store = load_readonly_store(path)
            self.assertEqual(store.task_status("task-absent"), {})
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_standalone_state_format_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"schema_version": 1, "tasks": {}, "checkpoint": None}), encoding="utf-8")
            self.assertEqual(load_readonly_store(path).task_status("task-absent"), {})

    def test_missing_state_file_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RecoveryStateError):
                load_readonly_store(Path(tmp) / "does-not-exist.json")

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
