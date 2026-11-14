import unittest

from scripts.distributed_loop_monitor import evaluate


def valid_state():
    return {
        "version": 1,
        "completed": [],
        "recovery_ai": {
            "schema_version": 1,
            "tasks": {},
            "checkpoint": None,
        },
    }


def valid_runs():
    return {"workflow_runs": []}


class DistributedLoopMonitorTests(unittest.TestCase):
    def evaluate(self, runs=None, state=None):
        return evaluate(
            valid_runs() if runs is None else runs,
            valid_state() if state is None else state,
            run_id="123",
            head_sha="a" * 40,
            started_at="2026-11-14T00:00:00Z",
        )

    def test_valid_read_only_state_passes_without_dispatch(self):
        report = self.evaluate()
        self.assertEqual(report["status"], "PASS")
        self.assertIs(report["dispatch_allowed"], False)

    def test_missing_actions_evidence_blocks(self):
        report = self.evaluate(runs={})
        self.assertEqual(report["status"], "BLOCKED")

    def test_missing_recovery_schema_blocks(self):
        report = self.evaluate(state={"version": 1})
        self.assertEqual(report["status"], "BLOCKED")

    def test_held_task_blocks(self):
        state = valid_state()
        state["recovery_ai"]["tasks"]["task-1"] = {"held": True}
        self.assertEqual(self.evaluate(state=state)["status"], "BLOCKED")

    def test_pending_resume_review_blocks(self):
        state = valid_state()
        state["recovery_ai"]["tasks"]["task-1"] = {
            "held": False, "resume_requires_review": True
        }
        self.assertEqual(self.evaluate(state=state)["status"], "BLOCKED")

    def test_malformed_task_record_blocks(self):
        state = valid_state()
        state["recovery_ai"]["tasks"]["task-1"] = "invalid"
        self.assertEqual(self.evaluate(state=state)["status"], "BLOCKED")

    def test_active_main_run_is_reported_but_not_dispatched(self):
        runs = {"workflow_runs": [{
            "name": "Distributed Autonomous Development Loop",
            "status": "in_progress",
        }]}
        report = self.evaluate(runs=runs)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["checks"]["main_loop_activity"]["active_run_count"], 1)
        self.assertFalse(report["dispatch_allowed"])


if __name__ == "__main__":
    unittest.main()
