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

    def test_protected_paths_always_require_maintainer_review(self):
        result = evaluate(
            base_sha="base", head_sha="head", actual_sha="head",
            base_counts=self.counts, head_counts=self.counts,
            files=["core/creator_critic.py", "tests/test_gate.py"],
        )
        self.assertEqual(result["quality_status"], "HOLD")
        self.assertIn("PROTECTED_PATHS_REQUIRE_MAINTAINER_REVIEW", result["reasons"])
        self.assertFalse(result["protected_changes_approved"])
        self.assertEqual(len(result["protected_files"]), 2)

    def test_total_test_count_decrease_holds_even_if_pass_count_is_unchanged(self):
        head = {**self.counts, "total": 95, "skipped": 0}
        result = evaluate(
            base_sha="base", head_sha="head", actual_sha="head",
            base_counts=self.counts, head_counts=head, files=[],
        )
        self.assertIn("TOTAL_TEST_COUNT_DECREASED", result["reasons"])

    def test_failed_head_test_holds(self):
        head = {**self.counts, "failed": 1, "passed": 94}
        result = evaluate(
            base_sha="base", head_sha="head", actual_sha="head",
            base_counts=self.counts, head_counts=head, files=[],
        )
        self.assertIn("HEAD_TESTS_NOT_CLEAN", result["reasons"])


if __name__ == "__main__":
    unittest.main()
