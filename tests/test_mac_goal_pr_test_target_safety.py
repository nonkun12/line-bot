from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "mac_goal_pr_test.sh"


class MacGoalPRTestTargetSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.git_log = self.root / "git-calls.log"
        git = self.bin_dir / "git"
        git.write_text(
            '#!/usr/bin/env bash\n'
            'printf "%s\\n" "$*" >> "$GIT_CALL_LOG"\n'
            'exit 99\n',
            encoding="utf-8",
        )
        git.chmod(0o755)

    def run_runner(self, target: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"
        env["GIT_CALL_LOG"] = str(self.git_log)
        return subprocess.run(
            ["bash", str(RUNNER), "123", target],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def git_calls(self) -> list[str]:
        if not self.git_log.exists():
            return []
        return self.git_log.read_text(encoding="utf-8").splitlines()

    def test_rejects_unsafe_targets_before_invoking_git(self) -> None:
        invalid = (
            "../outside.py",
            "tests/../../outside.py",
            "/tmp/outside.py",
            "-k",
            "tests//test_example.py",
            "tests/./test_example.py",
            "",
        )
        for target in invalid:
            with self.subTest(target=target):
                self.git_log.unlink(missing_ok=True)
                result = self.run_runner(target)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("ERROR:", result.stderr)
                self.assertEqual(self.git_calls(), [])

    def test_help_does_not_invoke_git(self) -> None:
        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"
        env["GIT_CALL_LOG"] = str(self.git_log)
        result = subprocess.run(
            ["bash", str(RUNNER), "--help"],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Usage:", result.stdout)
        self.assertEqual(self.git_calls(), [])

    def test_rejects_symlinked_target_component_before_running_pytest(self) -> None:
        repo = self.root / "line-bot"
        repo.mkdir()
        worktree = self.root / "line-bot-goal-pr123"
        external = self.root / "external"
        external.mkdir()
        (external / "test_example.py").write_text("def test_outside(): pass\n", encoding="utf-8")

        git = self.bin_dir / "git"
        git.write_text(
            '#!/usr/bin/env bash\n'
            'printf "%s\\n" "$*" >> "$GIT_CALL_LOG"\n'
            'case "$*" in\n'
            '  "rev-parse --show-toplevel") echo "$FAKE_REPO_ROOT" ;;\n'
            '  *"remote get-url origin"*) echo "https://github.com/nonkun12/line-bot.git" ;;\n'
            '  *"worktree add --detach"*) mkdir -p "$6/tests"; ln -s "$EXTERNAL_DIR" "$6/tests/linked" ;;\n'
            '  *) exit 0 ;;\n'
            'esac\n',
            encoding="utf-8",
        )
        git.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"
        env["GIT_CALL_LOG"] = str(self.git_log)
        env["FAKE_REPO_ROOT"] = str(repo)
        env["EXTERNAL_DIR"] = str(external)
        env["HOME"] = str(self.root / "home")

        result = subprocess.run(
            ["bash", str(RUNNER), "123", "tests/linked/test_example.py"],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("target traverses a symlink", result.stderr)
        self.assertTrue((worktree / "tests" / "linked").is_symlink())
        self.assertNotIn("pytest", result.stdout)


if __name__ == "__main__":
    unittest.main()
