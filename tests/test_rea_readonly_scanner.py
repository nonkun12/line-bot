"""Regression tests for the isolated read-only REA scanner."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.rea_readonly_scanner import ScanBlocked, scan_repository


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

    def test_dirty_worktree_blocks_sha_bound_evidence(self) -> None:
        self._write("scripts/good.py", "VALUE = 2\n")
        with self.assertRaises(ScanBlocked):
            scan_repository(self.root)

    def test_git_index_paths_preserve_newlines_and_unicode(self) -> None:
        self._write("scripts/日本語\nname.py", "VALUE = 2\\n")
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
