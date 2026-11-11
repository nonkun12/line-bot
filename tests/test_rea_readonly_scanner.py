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
        self.assertEqual(first["coverage"], "COMPLETE")
        self.assertEqual(len(first["evidence_sha256"]), 64)
        self.assertEqual(first["evidence_sha256"], second["evidence_sha256"])
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

    def test_workflow_write_all_permissions_are_high_severity_findings(self) -> None:
        self._write(
            ".github/workflows/broad-permissions.yml",
            "name: broad\npermissions: write-all\njobs:\n  check:\n    runs-on: ubuntu-latest\n",
        )
        self._commit()

        report = scan_repository(self.root)
        matches = [
            item for item in report["findings"]
            if item["category"] == "workflow_permission"
        ]
        self.assertEqual(report["status"], "FINDINGS")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["severity"], "HIGH")
        self.assertEqual(matches[0]["evidence"]["line"], 2)

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
            self.assertEqual(report["status"], "BLOCKED")
            self.assertFalse(report["complete"])
            self.assertEqual(report["coverage"], "INCOMPLETE")
            self.assertEqual(report["files_skipped_unsupported"], 1)
        finally:
            outside.unlink(missing_ok=True)


    def test_cloudflare_worker_and_d1_migrations_are_in_scope(self) -> None:
        self._write(
            "cloudflare/orca-test-api/src/index.js",
            """
            function safeEqual(a, b) { return a === b; }
            async function authorized() { return true; }
            async function claim() { return env.DB.batch([]); }
            const nonceLedger = "task_approval_nonces";
            const ownerHeader = "x-orca-task-owner";
            const claimToken = "claim_token";
            const outbox = "notification_outbox";
            const hmac = "crypto.subtle.sign";
            """,
        )
        self._write(
            "cloudflare/orca-test-api/migrations/0004_nonce.sql",
            """
            CREATE TABLE task_approval_nonces (
              approval_nonce TEXT PRIMARY KEY,
              task_id TEXT NOT NULL,
              approval_id TEXT NOT NULL UNIQUE,
              FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            );
            """,
        )
        self._commit()

        report = scan_repository(self.root)
        self.assertEqual(report["coverage"], "COMPLETE")
        self.assertFalse(report["scope"]["full_repository"])
        self.assertGreaterEqual(report["files_scanned"], 5)
        self.assertEqual(report["findings"], [])

    def test_missing_worker_security_contract_is_reported(self) -> None:
        self._write(
            "cloudflare/orca-test-api/src/index.js",
            "export default { fetch() { return new Response('ok'); } };\\n",
        )
        self._commit()
        report = scan_repository(self.root)
        findings = [
            item for item in report["findings"]
            if item["category"] == "cloudflare_worker_contract"
        ]
        self.assertEqual(report["status"], "FINDINGS")
        self.assertGreaterEqual(len(findings), 7)
        self.assertTrue(all(item["severity"] in {"HIGH", "CRITICAL"} for item in findings))

    def test_nonce_migration_without_replay_constraints_is_reported(self) -> None:
        self._write(
            "cloudflare/orca-test-api/migrations/0004_nonce.sql",
            "CREATE TABLE task_approval_nonces (approval_nonce TEXT, task_id TEXT);\\n",
        )
        self._commit()
        report = scan_repository(self.root)
        findings = [
            item for item in report["findings"]
            if item["category"] == "d1_migration_contract"
        ]
        self.assertEqual(len(findings), 3)
        self.assertEqual({item["severity"] for item in findings}, {"CRITICAL"})

    def test_root_config_is_scanned_for_verified_owner_header(self) -> None:
        self._write(
            "config.py",
            "def _get_orca_task_status():\\n    return httpx.get(url)\\n",
        )
        self._commit()
        report = scan_repository(self.root)
        self.assertIn(
            "missing_owner_header",
            {item["evidence"]["check"] for item in report["findings"]},
        )


if __name__ == "__main__":
    unittest.main()
