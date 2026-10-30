import unittest

from scripts.independent_qa_gate import evaluate, junit_counts


class IndependentQAGateTests(unittest.TestCase):
    def setUp(self):
        self.counts = {"total": 100, "passed": 95, "failed": 0, "errors": 0, "skipped": 5}

    def test_clean_matching_evidence_passes(self):
        result = evaluate(
            base_sha="base", head_sha="head", actual_sha="head",
            base_counts=self.counts, head_counts=self.counts, files=["app.py"],
        )
        self.assertEqual(result["quality_status"], "PASS")

    def test_sha_mismatch_holds(self):
        result = evaluate(
            base_sha="base", head_sha="expected", actual_sha="other",
            base_counts=self.counts, head_counts=self.counts, files=[],
        )
        self.assertIn("HEAD_SHA_MISMATCH", result["reasons"])

    def test_test_count_regression_holds(self):
        head = {**self.counts, "passed": 94, "total": 99}
        result = evaluate(
            base_sha="base", head_sha="head", actual_sha="head",
            base_counts=self.counts, head_counts=head, files=[],
        )
        self.assertIn("PASSED_TEST_COUNT_DECREASED", result["reasons"])

    def test_skip_increase_holds(self):
        head = {**self.counts, "skipped": 6, "passed": 94}
        result = evaluate(
            base_sha="base", head_sha="head", actual_sha="head",
            base_counts=self.counts, head_counts=head, files=[],
        )
        self.assertIn("SKIPPED_TEST_COUNT_INCREASED", result["reasons"])

    def test_protected_paths_require_explicit_approval(self):
        args = dict(
            base_sha="base", head_sha="head", actual_sha="head",
            base_counts=self.counts, head_counts=self.counts,
            files=["core/creator_critic.py", "tests/test_gate.py"],
        )
        blocked = evaluate(**args)
        approved = evaluate(**args, allow_protected=True)
        self.assertEqual(blocked["quality_status"], "HOLD")
        self.assertEqual(approved["quality_status"], "PASS")
        self.assertEqual(len(blocked["protected_files"]), 2)

    def test_failed_head_test_holds(self):
        head = {**self.counts, "failed": 1, "passed": 94}
        result = evaluate(
            base_sha="base", head_sha="head", actual_sha="head",
            base_counts=self.counts, head_counts=head, files=[],
        )
        self.assertIn("HEAD_TESTS_NOT_CLEAN", result["reasons"])


if __name__ == "__main__":
    unittest.main()
