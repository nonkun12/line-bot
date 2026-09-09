"""
Phase4a: pytest実行

安全設計:
- タイムアウトを必ず設定する(LLMが生成したコードが無限ループする事故を防ぐ)
- 自律開発Jobでは本番DBを使わず、Job専用の一時DBを利用する
"""

from __future__ import annotations

import os
import shlex
import subprocess

DEFAULT_TIMEOUT_SECONDS = 120


def _test_env(cwd: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if cwd:
        env["ENVIRONMENT"] = "test"
        env["DB_TYPE"] = "sqlite"
        env["CHAT_DB_PATH"] = os.path.join(cwd, ".worker-test-chat.db")
    return env


def run_tests(
    test_command: str = "pytest",
    cwd: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """
    pytestを実行し、結果を構造化して返す。

    Returns:
        dict:
            passed: bool
            returncode: Optional[int]
            stdout: str
            stderr: str
            timed_out: bool
    """

    try:
        result = subprocess.run(
            shlex.split(test_command),
            cwd=cwd,
            env=_test_env(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return {
            "passed": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": False,
        }

    except subprocess.TimeoutExpired as e:
        return {
            "passed": False,
            "returncode": None,
            "stdout": (e.stdout or ""),
            "stderr": (e.stderr or ""),
            "timed_out": True,
        }
