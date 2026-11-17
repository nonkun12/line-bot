"""Run a command while polling the shared GitHub emergency STOP marker."""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.emergency_stop import get_status


def _terminate_process_group(process: subprocess.Popen, stop_file: Path, grace_seconds: float) -> None:
    stop_file.touch(exist_ok=True)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=max(1.0, grace_seconds))


def run_with_shared_stop(
    command: list[str], *, repository: str, token: str,
    poll_seconds: float = 5.0, grace_seconds: float = 5.0,
) -> int:
    """Fail closed before spawn and terminate the full process group on STOP/uncertainty."""
    if not command or not repository.strip() or not token.strip():
        print("SHARED_STOP=BLOCKED reason=configuration_missing", file=sys.stderr, flush=True)
        return 82
    if poll_seconds <= 0 or grace_seconds < 0:
        print("SHARED_STOP=BLOCKED reason=invalid_poll_configuration", file=sys.stderr, flush=True)
        return 82
    try:
        if get_status(repository, token):
            print("SHARED_STOP=ACTIVE; refusing to start child", flush=True)
            return 82
    except Exception as exc:
        print(f"SHARED_STOP=UNVERIFIABLE error={type(exc).__name__}; refusing to start child", file=sys.stderr, flush=True)
        return 82

    stop_file = Path(tempfile.gettempdir()) / f"line-bot-shared-stop-{os.getpid()}-{time.monotonic_ns()}.stop"
    child_env = os.environ.copy()
    child_env["AUTONOMOUS_STOP_FILE"] = str(stop_file)
    process: subprocess.Popen | None = None
    try:
        process = subprocess.Popen(command, env=child_env, start_new_session=True)
        while process.poll() is None:
            try:
                active = get_status(repository, token)
            except Exception as exc:
                print(f"SHARED_STOP=UNVERIFIABLE error={type(exc).__name__}; terminating child", file=sys.stderr, flush=True)
                _terminate_process_group(process, stop_file, grace_seconds)
                return 82
            if active:
                print("SHARED_STOP=ACTIVE; terminating child process group", flush=True)
                _terminate_process_group(process, stop_file, grace_seconds)
                return 82
            time.sleep(poll_seconds)
        return int(process.returncode or 0)
    except Exception as exc:
        if process is not None and process.poll() is None:
            _terminate_process_group(process, stop_file, grace_seconds)
        print(f"SHARED_STOP=BLOCKED error={type(exc).__name__}", file=sys.stderr, flush=True)
        return 82
    finally:
        try:
            stop_file.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "nonkun12/line-bot"))
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--grace-seconds", type=float, default=5.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    return run_with_shared_stop(
        command, repository=args.repository, token=token,
        poll_seconds=args.poll_seconds, grace_seconds=args.grace_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
