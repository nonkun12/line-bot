"""Tests for the fail-closed post-generation REA adapter."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.rea_post_generation_gate import (
    PostGenerationREABlocked,
    verify_generated_commit,
)


class PostGenerationREAGateTests(unittest.TestCase):
    def _pass_report(self):
        return {
            "base_sha": "a" * 40,
            "target_sha": "b" * 40,
            "diff_sha256": "c" * 64,
            "complete": True,
            "status": "PASS",
            "findings_count": 0,
            "findings": [],
            "capabilities": {
                "read_only": True,
                "executes_project_code": False,
            },
        }

    @patch("scripts.rea_post_generation_gate.scan_commit_diff")
    def test_accepts_only_exact_complete_clean_report(self, scanner):
        scanner.return_value = self._pass_report()
        report = verify_generated_commit(
            ".", base_sha="a" * 40, target_sha="b" * 40
        )
        self.assertEqual(report["target_sha"], "b" * 40)

    @patch("scripts.rea_post_generation_gate.scan_commit_diff")
    def test_blocks_findings_even_when_scanner_status_is_pass(self, scanner):
        report = self._pass_report()
        report["findings"] = [{"severity": "HIGH"}]
        scanner.return_value = report
        with self.assertRaises(PostGenerationREABlocked):
            verify_generated_commit(".", base_sha="a" * 40, target_sha="b" * 40)

    @patch("scripts.rea_post_generation_gate.scan_commit_diff")
    def test_blocks_incomplete_or_wrong_sha_evidence(self, scanner):
        report = self._pass_report()
        report["complete"] = False
        scanner.return_value = report
        with self.assertRaises(PostGenerationREABlocked):
            verify_generated_commit(".", base_sha="a" * 40, target_sha="b" * 40)

    @patch("scripts.rea_post_generation_gate.scan_commit_diff")
    def test_blocks_scanner_errors(self, scanner):
        scanner.side_effect = RuntimeError("network or git unavailable")
        with self.assertRaises(PostGenerationREABlocked):
            verify_generated_commit(".", base_sha="a" * 40, target_sha="b" * 40)


if __name__ == "__main__":
    unittest.main()
