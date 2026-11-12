from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/distributed-autonomous-loop.yml")


class DistributedLoopGlobalHoldWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")

    def test_initial_hold_gate_runs_before_state_reads_and_task_work(self):
        gate = self.source.index("id: global_hold_preflight")
        state_read = self.source.index("- name: Load durable loop state")
        task_run = self.source.index("- name: Run one bounded autonomous task")
        self.assertLess(gate, state_read)
        self.assertLess(gate, task_run)

    def test_mutating_steps_have_immediate_global_hold_rechecks(self):
        pairs = (
            ("id: global_hold_before_task", "- name: Run one bounded autonomous task"),
            ("id: global_hold_before_issues", "- name: Create bounded review-only task issues from analyzer findings"),
            ("id: global_hold_before_publish", "- name: Publish verified development branch"),
            ("id: global_hold_before_state", "- name: Persist completed task state"),
            ("id: global_hold_before_recovery", "- name: Persist Recovery AI durable state"),
            ("id: global_hold_before_sheets", "- name: Record distributed run result to Google Sheets"),
            ("id: global_hold_before_render", "- name: Publish cloud Orca runtime snapshot to Render"),
            ("id: global_hold_before_line", "- name: Notify LINE of distributed loop final report"),
        )
        for gate, action in pairs:
            with self.subTest(action=action):
                self.assertLess(self.source.index(gate), self.source.index(action))

    def test_all_gates_use_required_d1_secrets_and_shared_checker(self):
        self.assertGreaterEqual(self.source.count("secrets.ORCA_TASK_API_URL"), 8)
        self.assertGreaterEqual(self.source.count("secrets.ORCA_TASK_API_TOKEN"), 8)
        self.assertGreaterEqual(self.source.count("python -m scripts.check_orca_global_hold"), 8)

    def test_sheets_write_is_skipped_when_hold_gate_does_not_pass(self):
        self.assertIn(
            "if: ${{ always() && steps.global_hold_before_sheets.outcome == 'success' }}",
            self.source,
        )

    def test_hold_failure_is_reported_as_blocked(self):
        self.assertIn('touch /tmp/orca-global-hold-blocked', self.source)
        self.assertIn('Path("/tmp/orca-global-hold-blocked").exists()', self.source)
        self.assertIn('"orca_global_hold_active_or_unavailable"', self.source)


if __name__ == "__main__":
    unittest.main()
