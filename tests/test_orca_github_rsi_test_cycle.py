import unittest

from scripts.orca_github_rsi_test_cycle import (
    SUITES, diagnose, hypothesize, run_cycle, select,
)


def result(suite_id, status="PASS", timed_out=False):
    return {
        "suite_id": suite_id, "status": status, "timed_out": timed_out,
        "exit_code": 0 if status == "PASS" else 1,
        "tests_run": 1, "failure_count": 0 if status == "PASS" else 1,
    }


class OrcaRsiTestCycleTests(unittest.TestCase):
    def test_targets_are_a_fixed_allowlist(self):
        self.assertEqual(len(SUITES), 6)
        self.assertEqual(len({row[1] for row in SUITES}), len(SUITES))
        self.assertTrue(all(name.startswith("test_orca_") and name.endswith(".py")
                            for _, name in SUITES))

    def test_diagnosis_does_not_claim_root_cause(self):
        findings = diagnose([result("worker-boundary", "FAIL")])
        self.assertEqual(findings[0]["classification"], "test_failure")
        proposal = hypothesize(findings)
        self.assertEqual(proposal[0]["confidence"], "unverified")
        self.assertIn("may exist", proposal[0]["hypothesis"])

    def test_timeout_is_not_automatically_retried(self):
        rows = [result("worker-boundary", "TIMEOUT", True)]
        self.assertEqual(diagnose(rows)[0]["classification"], "timeout")
        self.assertEqual(select(rows, []), "BLOCKED")

    def test_selection_requires_clean_baseline_or_human_review(self):
        good = [result(suite_id) for suite_id, _, _ in SUITES]
        self.assertEqual(select(good, []), "PASS")
        failed = [result("worker-boundary", "FAIL")]
        self.assertEqual(select(failed, [result("worker-boundary")]),
                         "FLAKY_REVIEW_REQUIRED")
        self.assertEqual(select(failed, [result("worker-boundary", "FAIL")]),
                         "BLOCKED")

    def test_cycle_preserves_all_five_stages_and_no_mutation(self):
        def fake_runner(suite_id, filename):
            return result(suite_id)
        report = run_cycle(runner=fake_runner, created_at="2026-11-16T00:00:00Z")
        self.assertEqual(list(report["stages"]), [
            "evaluate", "diagnose", "hypothesize", "experiment", "select_evolve",
        ])
        self.assertEqual(report["stages"]["select_evolve"]["status"], "PASS")
        self.assertFalse(report["stages"]["select_evolve"]["source_mutation"])
        self.assertFalse(report["execution_boundary"]["llm_used"])
        self.assertFalse(report["execution_boundary"]["queue_claimed"])


if __name__ == "__main__":
    unittest.main()
