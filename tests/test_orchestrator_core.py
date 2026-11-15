import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.orchestrator_core import PlanError, build_plan
from scripts.orchestrator_dashboard import render_dashboard


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
        for key in (
            "execution_performed", "dispatch_performed", "repository_modified",
            "push_performed", "pull_request_created", "merge_performed",
            "deployment_performed",
        ):
            self.assertFalse(plan[key], key)

    def test_cli_empty_queue_smoke_test(self):
        document = payload([])
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "empty-queue.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            script = Path(__file__).resolve().parents[1] / "scripts" / "orchestrator_core.py"
            result = subprocess.run(
                [sys.executable, str(script), "--input", str(input_path)],
                capture_output=True, text=True, check=False, timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "NO_TASK")
        self.assertIsNone(plan["selected_candidate"])
        self.assertFalse(plan["execution_performed"])
        self.assertFalse(plan["dispatch_performed"])
        self.assertFalse(plan["repository_modified"])
        self.assertFalse(plan["push_performed"])
        self.assertFalse(plan["pull_request_created"])
        self.assertFalse(plan["merge_performed"])
        self.assertFalse(plan["deployment_performed"])

    def test_cli_rejects_output_file_option(self):
        document = payload([])
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "empty-queue.json"
            output_path = Path(tmp) / "must-not-be-created.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            script = Path(__file__).resolve().parents[1] / "scripts" / "orchestrator_core.py"
            result = subprocess.run(
                [sys.executable, str(script), "--input", str(input_path),
                 "--output", str(output_path)],
                capture_output=True, text=True, check=False, timeout=15,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output_path.exists())

    def test_priority_then_id_is_deterministic(self):
        plan = build_plan(payload([
            {"id": "z", "priority": 5, "execution_approved": True},
            {"id": "b", "priority": 9, "execution_approved": True},
            {"id": "a", "priority": 9, "execution_approved": True},
        ]))
        self.assertEqual(plan["selected_candidate"], "a")

    def test_dependency_must_be_done(self):
        plan = build_plan(payload([
            {"id": "setup", "execution_approved": True},
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

    def test_unverified_approval_is_never_execution_authorization(self):
        plan = build_plan(payload([
            {"id": "highest-unapproved", "priority": 10},
            {"id": "lower-caller-approved", "priority": 5, "execution_approved": True},
        ]))
        self.assertEqual(plan["status"], "PLAN_READY")
        self.assertEqual(plan["selected_candidate"], "highest-unapproved")
        self.assertFalse(plan["execution_authorized"])
        self.assertFalse(plan["approval_evidence_verified"])
        self.assertFalse(plan["budget_evidence_verified"])
        self.assertIn("approval_evidence_unverified", plan["reasons"])
        self.assertFalse(plan["execution_performed"])

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

    def test_non_string_status_is_rejected_without_crashing(self):
        with self.assertRaisesRegex(PlanError, "invalid_task_status"):
            build_plan(payload([{"id": "x", "status": []}]))

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

    def test_dashboard_renders_empty_queue_and_read_only_flags(self):
        rendered = render_dashboard(payload([]))
        self.assertIn("**Status:** NO_TASK", rendered)
        self.assertIn("Selected candidate:** none", rendered)
        self.assertIn("execution=false", rendered)
        self.assertIn("dispatch=false", rendered)
        self.assertIn("merge=false", rendered)
        self.assertIn("Snapshot renderer only", rendered)

    def test_dashboard_cli_smoke_test(self):
        document = payload([
            {"id": "audit", "title": "Read-only audit", "execution_approved": False},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "queue.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            script = Path(__file__).resolve().parents[1] / "scripts" / "orchestrator_dashboard.py"
            result = subprocess.run(
                [sys.executable, str(script), "--input", str(input_path)],
                capture_output=True, text=True, check=False, timeout=15,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("**Status:** HOLD", result.stdout)
        self.assertIn("Read-only audit", result.stdout)
        self.assertIn("execution=false", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_dashboard_renders_task_state_and_escapes_table_values(self):
        rendered = render_dashboard(payload([
            {"id": "task|one", "title": "Audit\n|details", "priority": 4,
             "estimated_minutes": 3, "execution_approved": True},
        ]))
        self.assertIn("task\\|one", rendered)
        self.assertIn(r"Audit \|details", rendered)
        self.assertIn("READY", rendered)
        self.assertIn("yes", rendered)


if __name__ == "__main__":
    unittest.main()
