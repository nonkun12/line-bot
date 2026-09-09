"""Safe pytest runner used by both interactive and autonomous agents."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile

DEFAULT_TIMEOUT_SECONDS = 120


def _test_env(cwd: str | None) -> tuple[dict[str, str], str | None]:
    env = os.environ.copy()
    scratch_db = None
    if cwd:
        env["ENVIRONMENT"] = "test"
        env["DB_TYPE"] = "sqlite"
        fd, scratch_db = tempfile.mkstemp(prefix="worker-test-", suffix=".db", dir=cwd)
        os.close(fd)
        env["CHAT_DB_PATH"] = scratch_db
    return env, scratch_db


def _cleanup_test_db(scratch_db: str | None) -> None:
    if not scratch_db:
        return
    for path in (scratch_db, f"{scratch_db}-wal", f"{scratch_db}-shm"):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def run_tests(
    test_command: str = "pytest",
    cwd: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    env, scratch_db = _test_env(cwd)
    try:
        result = subprocess.run(
            shlex.split(test_command),
            cwd=cwd,
            env=env,
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
            "test_db_path": scratch_db,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "passed": False,
            "returncode": None,
            "stdout": e.stdout or "",
            "stderr": e.stderr or "",
            "timed_out": True,
            "test_db_path": scratch_db,
        }
    finally:
        _cleanup_test_db(scratch_db)
