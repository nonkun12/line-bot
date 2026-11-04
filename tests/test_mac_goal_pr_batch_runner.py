from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_RUNNER = REPO_ROOT / "scripts" / "mac_goal_pr_batch_test.sh"


class MacGoalPRBatchRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.scripts = self.root / "scripts"
        self.scripts.mkdir()
        shutil.copy2(BATCH_RUNNER, self.scripts / BATCH_RUNNER.name)
        self.call_log = self.root / "calls.log"
        (self.scripts / "mac_goal_pr_test.sh").write_text(
            '#!/usr/bin/env bash\n'
            'printf "%s\\t%s\\n" "$1" "$2" >> "$CALL_LOG"\n'
            'if [[ "$FAIL_PR" == "$1" ]]; then exit 7; fi\n'
            'exit 0\n',
            encoding="utf-8",
        )

    def run_batch(self, selector: str, *, fail_pr: str = "", target: str = "tests/example.py"):
        env = os.environ.copy()
        env["CALL_LOG"] = str(self.call_log)
        env["FAIL_PR"] = fail_pr
        args = ["bash", str(self.scripts / BATCH_RUNNER.name), selector]
        if target is not None:
            args.append(target)
        return subprocess.run(args, text=True, capture_output=True, env=env, check=False)

    def recorded_calls(self) -> list[str]:
        if not self.call_log.exists():
            return []
        return self.call_log.read_text(encoding="utf-8").splitlines()

    def test_rejects_invalid_and_duplicate_selectors_before_running_any_pr(self) -> None:
        invalid = ("0", "1251,1251", "1251-1250", "1-51", "01251", "1251,,1252")
        for selector in invalid:
            with self.subTest(selector=selector):
                self.call_log.unlink(missing_ok=True)
                result = self.run_batch(selector)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(self.recorded_calls(), [])
                self.assertIn("ERROR:", result.stderr)

    def test_expands_ranges_and_explicit_prs_and_forwards_test_target(self) -> None:
        result = self.run_batch("1251-1253,1255", target="tests/test_goal_job_chain.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.recorded_calls(),
            [
                "1251\ttests/test_goal_job_chain.py",
                "1252\ttests/test_goal_job_chain.py",
                "1253\ttests/test_goal_job_chain.py",
                "1255\ttests/test_goal_job_chain.py",
            ],
        )
        self.assertIn("TOTAL: 4  PASS: 4  FAIL: 0", result.stdout)

    def test_continues_after_a_pr_fails_and_returns_failure(self) -> None:
        result = self.run_batch("1251-1253", fail_pr="1252")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            self.recorded_calls(),
            [
                "1251\ttests/example.py",
                "1252\ttests/example.py",
                "1253\ttests/example.py",
            ],
        )
        self.assertIn("#1252 FAIL (exit 7)", result.stdout)
        self.assertIn("TOTAL: 3  PASS: 2  FAIL: 1", result.stdout)

    def test_rejects_overlapping_ranges_before_running_any_pr(self) -> None:
        result = self.run_batch("1251-1253,1253-1255")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.recorded_calls(), [])
        self.assertIn("duplicate PR number: 1253", result.stderr)

    def test_accepts_nine_digit_pr_number_and_rejects_ten_digits(self) -> None:
        accepted = self.run_batch("999999999")
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        self.assertEqual(self.recorded_calls(), ["999999999\ttests/example.py"])

        self.call_log.unlink(missing_ok=True)
        rejected = self.run_batch("1000000000")
        self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
        self.assertEqual(self.recorded_calls(), [])
        self.assertIn("ERROR:", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
