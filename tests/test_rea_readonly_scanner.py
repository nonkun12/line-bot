"""Regression tests for the isolated read-only REA scanner."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.rea_readonly_scanner import ScanBlocked, scan_commit_diff, scan_repository


class ReadonlyScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "rea-tests@example.invalid"],
            cwd=self.root, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "REA tests"],
            cwd=self.root, check=True,
        )
        self._write("scripts/good.py", "VALUE = 1\n")
        self._write("tests/valid.json", '{"ok": true}\n')
        self._write(
            ".github/workflows/safe.yml",
            "env:\n  AUTO_APPLY_PATCH: \"false\"\n  AUTO_DEPLOY: \"false\"\n",
        )
        self._commit()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _commit(self) -> None:
        subprocess.run(["git", "add", "--all"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "fixture"],
            cwd=self.root, check=True,
        )

    def test_clean_scan_is_repeatable_and_read_only(self) -> None:
        before = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=self.root, text=True
        )
        first = scan_repository(self.root)
        second = scan_repository(self.root)
        after = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=self.root, text=True
        )
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "PASS")
        self.assertTrue(first["capabilities"]["read_only"])
        self.assertFalse(first["capabilities"]["executes_project_code"])
        self.assertFalse(first["capabilities"]["patches_tasks_hold_merge_deploy"])
        self.assertEqual(before, after)

    def test_reports_syntax_and_enabled_safety_flag_without_source_text(self) -> None:
        self._write("scripts/bad.py", "def broken(:\n  TOKEN = 'do-not-print-this-secret'\n")
        self._write(
            ".github/workflows/unsafe.yml",
            "env:\n  AUTO_DEPLOY: true\n",
        )
        self._commit()

        report = scan_repository(self.root)
        rendered = json.dumps(report, sort_keys=True)
        categories = {item["category"] for item in report["findings"]}
        self.assertEqual(report["status"], "FINDINGS")
        self.assertIn("python_syntax", categories)
        self.assertIn("safety_flag", categories)
        self.assertNotIn("do-not-print-this-secret", rendered)
        self.assertNotIn("broken(:", rendered)

    def test_commit_diff_scans_generated_output_and_binds_hashes(self) -> None:
        base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True).strip()
        self._write("scripts/generated.py", "def broken(:\\n  pass\\n")
        self._commit()
        target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True).strip()

        report = scan_commit_diff(self.root, base_sha=base, target_sha=target)
        self.assertEqual(report["base_sha"], base)
        self.assertEqual(report["target_sha"], target)
        self.assertEqual(len(report["diff_sha256"]), 64)
        self.assertEqual(report["status"], "FINDINGS")
        self.assertIn("python_syntax", {item["category"] for item in report["findings"]})
        self.assertTrue(report["capabilities"]["read_only"])


    def test_commit_diff_allows_only_reviewed_line_development_entrypoint(self) -> None:
        base = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        self._write("line_development.py", "VALUE = 2\n")
        self._commit()
        target = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()

        report = scan_commit_diff(self.root, base_sha=base, target_sha=target)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["findings_count"], 0)
        self.assertEqual(report["changed_paths"], ["line_development.py"])

    def test_commit_diff_requires_human_review_for_distributed_loop_trigger(self) -> None:
        base = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        self._write("distributed_loop_trigger.py", "VALUE = 2\n")
        self._commit()
        target = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()

        report = scan_commit_diff(self.root, base_sha=base, target_sha=target)
        self.assertEqual(report["findings_count"], 1)
        self.assertEqual({item["category"] for item in report["findings"]}, {"manual_review_required"})
        self.assertEqual(report["changed_paths"], ["distributed_loop_trigger.py"])
        finding = next(
            item for item in report["findings"]
            if item["category"] == "manual_review_required"
        )
        self.assertEqual(finding["severity"], "HIGH")
        self.assertEqual(
            finding["evidence"]["check"],
            "sensitive_entrypoint_requires_human_review",
        )

    def test_commit_diff_requires_human_review_when_dispatcher_is_renamed(self) -> None:
        self._write("distributed_loop_trigger.py", "VALUE = 3\n")
        self._commit()
        base = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        subprocess.run(
            ["git", "mv", "distributed_loop_trigger.py", "scripts/moved_dispatch.py"],
            cwd=self.root, check=True,
        )
        self._commit()
        target = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()

        report = scan_commit_diff(self.root, base_sha=base, target_sha=target)
        self.assertEqual(report["status"], "FINDINGS")
        self.assertEqual(
            report["changed_paths"],
            ["distributed_loop_trigger.py", "scripts/moved_dispatch.py"],
        )
        categories = {item["category"] for item in report["findings"]}
        self.assertIn("manual_review_required", categories)
        self.assertIn("deleted_file", categories)
        manual = next(
            item for item in report["findings"]
            if item["category"] == "manual_review_required"
        )
        self.assertEqual(manual["severity"], "HIGH")

    def test_commit_diff_still_blocks_other_repository_root_files(self) -> None:
        base = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        self._write("app.py", "VALUE = 2\n")
        self._commit()
        target = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()

        report = scan_commit_diff(self.root, base_sha=base, target_sha=target)
        self.assertEqual(report["status"], "FINDINGS")
        finding = next(
            item for item in report["findings"]
            if item["category"] == "path_policy"
        )
        self.assertEqual(finding["category"], "path_policy")
        self.assertEqual(finding["evidence"]["path"], "app.py")
        self.assertEqual(finding["severity"], "CRITICAL")

    def test_commit_diff_blocks_invalid_sha(self) -> None:
        with self.assertRaises(ScanBlocked):
            scan_commit_diff(self.root, base_sha="not-a-sha", target_sha="0" * 40)

    def test_commit_diff_blocks_unrelated_base_history(self) -> None:
        target = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        tree = subprocess.check_output(
            ["git", "rev-parse", f"{target}^{{tree}}"], cwd=self.root, text=True
        ).strip()
        unrelated = subprocess.check_output(
            ["git", "commit-tree", tree, "-m", "unrelated history"],
            cwd=self.root, text=True,
        ).strip()
        with self.assertRaises(ScanBlocked):
            scan_commit_diff(self.root, base_sha=unrelated, target_sha=target)

    def test_commit_diff_blocks_unrelated_target_history(self) -> None:
        base = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        subprocess.run(
            ["git", "checkout", "--orphan", "unrelated-history"],
            cwd=self.root, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "rm", "-rf", "."], cwd=self.root, check=True,
            capture_output=True,
        )
        self._write("scripts/unrelated.py", "VALUE = 9\n")
        self._commit()
        target = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        with self.assertRaisesRegex(ScanBlocked, "base_commit_not_ancestor"):
            scan_commit_diff(self.root, base_sha=base, target_sha=target)

    def test_commit_diff_flags_deleted_tests(self) -> None:
        base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True).strip()
        (self.root / "tests" / "valid.json").unlink()
        self._commit()
        target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True).strip()
        report = scan_commit_diff(self.root, base_sha=base, target_sha=target)
        self.assertIn("deleted_file", {item["category"] for item in report["findings"]})

    def test_dirty_worktree_blocks_sha_bound_evidence(self) -> None:
        self._write("scripts/good.py", "VALUE = 2\n")
        with self.assertRaises(ScanBlocked):
            scan_repository(self.root)
    def test_untracked_file_blocks_sha_bound_evidence(self) -> None:
        self._write("tests/untracked.txt", "UNTRACKED = 1\n")
        with self.assertRaises(ScanBlocked):
            scan_repository(self.root)

    def test_git_index_paths_preserve_newlines_and_unicode(self) -> None:
        self._write("scripts/日本語\nname.py", "VALUE = 2\n")
        self._commit()
        report = scan_repository(self.root)
        self.assertEqual(report["status"], "PASS")
        self.assertGreaterEqual(report["files_scanned"], 4)

    def test_assume_unchanged_index_flag_blocks_scan(self) -> None:
        subprocess.run(
            ["git", "update-index", "--assume-unchanged", "scripts/good.py"],
            cwd=self.root, check=True,
        )
        with self.assertRaises(ScanBlocked):
            scan_repository(self.root)

    def test_skip_worktree_index_flag_blocks_scan(self) -> None:
        subprocess.run(
            ["git", "update-index", "--skip-worktree", "scripts/good.py"],
            cwd=self.root, check=True,
        )
        with self.assertRaises(ScanBlocked):
            scan_repository(self.root)

    def test_symlink_is_not_followed(self) -> None:
        outside = self.root.parent / "rea-outside-secret.txt"
        outside.write_text("private marker", encoding="utf-8")
        try:
            link = self.root / "scripts" / "outside.py"
            link.symlink_to(outside)
            self._commit()
            report = scan_repository(self.root)
            self.assertNotIn("private marker", json.dumps(report))
            self.assertNotIn("outside.py", [f["evidence"]["path"] for f in report["findings"]])
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
