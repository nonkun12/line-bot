import unittest

from scripts.orchestrator_core import PlanError, build_plan


def payload(tasks, **overrides):
    doc = {
        "schema_version": 1,
        "global_hold": False,
        "budget": {"limit_minutes": 120, "consumed_minutes": 10, "reserved_minutes": 10},
        "tasks": tasks,
    }
    doc.update(overrides)
    return doc


class OrchestratorCoreTests(unittest.TestCase):
    def test_empty_queue_is_no_task_and_never_executes(self):
        plan = build_plan(payload([]))
        self.assertEqual(plan["status"], "NO_TASK")
        self.assertIsNone(plan["selected_candidate"])
        self.assertFalse(plan["execution_performed"])
        self.assertFalse(plan["dispatch_performed"])

    def test_priority_then_id_is_deterministic(self):
        plan = build_plan(payload([
            {"id": "z", "priority": 5, "execution_approved": True},
            {"id": "b", "priority": 9, "execution_approved": True},
            {"id": "a", "priority": 9, "execution_approved": True},
        ]))
        self.assertEqual(plan["selected_candidate"], "a")

    def test_dependency_must_be_done(self):
        plan = build_plan(payload([
            {"id": "setup"},
            {"id": "work", "depends_on": ["setup"], "execution_approved": True},
        ]))
        states = {task["id"]: task["planning_state"] for task in plan["tasks"]}
        self.assertEqual(states, {"setup": "READY", "work": "WAITING"})
        self.assertEqual(plan["selected_candidate"], "setup")

    def test_global_hold_blocks_selection(self):
        plan = build_plan(payload(
            [{"id": "work", "execution_approved": True}],
            global_hold=True,
        ))
        self.assertEqual(plan["status"], "HOLD")
        self.assertIsNone(plan["selected_candidate"])
        self.assertIn("global_hold", plan["reasons"])

    def test_missing_approval_fails_closed(self):
        plan = build_plan(payload([{"id": "work"}]))
        self.assertEqual(plan["status"], "HOLD")
        self.assertIn("execution_approval_missing", plan["reasons"])
        self.assertIsNone(plan["selected_candidate"])

    def test_budget_exhaustion_blocks(self):
        plan = build_plan(payload(
            [{"id": "work", "execution_approved": True}],
            budget={"limit_minutes": 20, "consumed_minutes": 10, "reserved_minutes": 10},
        ))
        self.assertEqual(plan["status"], "HOLD")
        self.assertIn("budget_exhausted", plan["reasons"])

    def test_estimate_must_fit_remaining_budget(self):
        plan = build_plan(payload([
            {"id": "work", "estimated_minutes": 101, "execution_approved": True},
        ]))
        self.assertEqual(plan["status"], "HOLD")
        self.assertIn("insufficient_remaining_budget", plan["reasons"])

    def test_missing_dependency_is_rejected(self):
        with self.assertRaisesRegex(PlanError, "dependency_not_found"):
            build_plan(payload([{"id": "work", "depends_on": ["missing"]}]))

    def test_cycle_is_rejected(self):
        with self.assertRaisesRegex(PlanError, "dependency_cycle"):
            build_plan(payload([
                {"id": "a", "depends_on": ["b"]},
                {"id": "b", "depends_on": ["a"]},
            ]))

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaisesRegex(PlanError, "duplicate_task_id"):
            build_plan(payload([{"id": "x"}, {"id": "x"}]))

    def test_unknown_status_is_rejected(self):
        with self.assertRaisesRegex(PlanError, "invalid_task_status"):
            build_plan(payload([{"id": "x", "status": "magic"}]))

    def test_running_and_failed_tasks_are_not_candidates(self):
        plan = build_plan(payload([
            {"id": "running", "status": "running", "execution_approved": True},
            {"id": "failed", "status": "failed", "execution_approved": True},
            {"id": "ready", "execution_approved": True},
        ]))
        self.assertEqual(plan["selected_candidate"], "ready")

    def test_output_is_deterministic(self):
        doc = payload([
            {"id": "b", "priority": 1, "execution_approved": True},
            {"id": "a", "priority": 1, "execution_approved": True},
        ])
        self.assertEqual(build_plan(doc), build_plan(doc))


if __name__ == "__main__":
    unittest.main()
