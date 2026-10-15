"""Tests for the opt-in Recovery AI -> local fm advisory bridge."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.recovery_ai import RecoveryDecision, RecoveryStore
from scripts.recovery_ai_local_advisor import advise_for_decision, record_failure_and_advise


def decision(action="REPAIR_ONCE"):
    return RecoveryDecision(
        action=action, reason="test", task_id="task-1", fingerprint="abc",
        consecutive_failures=1,
    )


class LocalAdvisorBridgeTests(unittest.TestCase):
    def test_allowed_repair_returns_advisory_only(self):
        advisor = Mock(return_value={
            "diagnosis": "原因候補", "action": "テストを調査", "risk": "変更しない",
        })
        result = advise_for_decision(
            decision(), "test_regression", ["tests/test_example.py::test_case"],
            advisor=advisor,
        )
        self.assertEqual(result.status, "ADVISORY_ONLY")
        self.assertEqual(result.decision_action, "REPAIR_ONCE")
        self.assertIsNotNone(result.suggestion)
        advisor.assert_called_once_with(
            "task-1", "test_regression", ["tests/test_example.py::test_case"]
        )

    def test_non_repair_decision_never_calls_advisor(self):
        advisor = Mock()
        result = advise_for_decision(
            decision("HOLD"), "test_regression", advisor=advisor
        )
        self.assertEqual(result.status, "SKIPPED")
        advisor.assert_not_called()

    def test_security_category_never_calls_advisor(self):
        advisor = Mock()
        result = advise_for_decision(
            decision(), "security_violation", advisor=advisor
        )
        self.assertEqual(result.status, "SKIPPED")
        advisor.assert_not_called()

    def test_advisor_failure_fails_closed(self):
        from scripts.recovery_ai_fm_advisor import AdvisorError
        advisor = Mock(side_effect=AdvisorError("not available"))
        result = advise_for_decision(
            decision(), "timeout", advisor=advisor
        )
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertIsNone(result.suggestion)
        self.assertEqual(result.decision_action, "REPAIR_ONCE")

    def test_invalid_advisor_output_is_not_trusted(self):
        result = advise_for_decision(
            decision(), "timeout",
            advisor=Mock(return_value={"diagnosis": "x", "action": "y", "risk": "z",
                                       "command": "unsafe"}),
        )
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertIsNone(result.suggestion)

    def test_bridge_does_not_mutate_recovery_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "state.json")
            original = store.record_failure("task-1", "test_regression")
            before = store.task_status("task-1")
            advise_for_decision(
                original, "test_regression",
                advisor=Mock(return_value={
                    "diagnosis": "原因候補", "action": "調査", "risk": "変更しない",
                }),
            )
            self.assertEqual(store.task_status("task-1"), before)

    def test_real_store_decision_controls_advisor_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "state.json")
            advisor = Mock(return_value={"diagnosis": "原因候補", "action": "調査", "risk": "変更しない"})
            decision_result, advice = record_failure_and_advise(store, "task-1", "test_regression", ["tests/test_example.py"], advisor=advisor)
            self.assertEqual(decision_result.action, "REPAIR_ONCE")
            self.assertEqual(advice.status, "ADVISORY_ONLY")
            advisor.assert_called_once()

    def test_real_store_hold_prevents_local_advisor(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "state.json")
            store.record_failure("task-1", "test_regression")
            store.record_failure("task-1", "test_regression")
            advisor = Mock()
            decision_result, advice = record_failure_and_advise(store, "task-1", "test_regression", advisor=advisor)
            self.assertEqual(decision_result.action, "HOLD")
            self.assertEqual(advice.status, "SKIPPED")
            advisor.assert_not_called()

    def test_persistence_error_prevents_advisor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("{invalid", encoding="utf-8")
            store = RecoveryStore(path)
            advisor = Mock()
            from scripts.recovery_ai import RecoveryStateError
            with self.assertRaises(RecoveryStateError):
                record_failure_and_advise(store, "task-1", "test_regression", advisor=advisor)
            advisor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
