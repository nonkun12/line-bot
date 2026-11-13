"""Fail-closed in-flight safety watcher for the distributed loop."""
from __future__ import annotations
import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.distributed_loop_30m_gate import GateBlocked, check_budget, check_global_hold

def check_remote_stop():
    fetch = subprocess.run(
        ["git", "-C", str(ROOT), "fetch", "--quiet", "--no-tags", "--depth=1", "origin", "main"],
        capture_output=True, timeout=15
    )
    if fetch.returncode != 0:
        raise GateBlocked("remote_stop_state_unavailable")
    result = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", "FETCH_HEAD:.autonomous-loop.stop"],
        capture_output=True, timeout=10
    )
    if result.returncode == 0:
        raise GateBlocked("remote_stop_switch_active")
    if result.returncode != 1:
        raise GateBlocked("remote_stop_state_unreadable")

def check_once(stop_file: Path):
    try:
        check_remote_stop()
        check_global_hold()
        check_budget(datetime.now(timezone.utc))
        return True
    except Exception as exc:
        try:
            stop_file.parent.mkdir(parents=True, exist_ok=True)
            stop_file.touch(exist_ok=True)
        except OSError:
            raise SystemExit(2)
        reason = exc.args[0] if isinstance(exc, GateBlocked) and exc.args else "safety_watcher_error"
        print("DISTRIBUTED_LOOP_STOP: " + str(reason), flush=True)
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args()
    if not 5 <= args.interval <= 60:
        raise SystemExit("--interval must be 5..60 seconds")
    while True:
        if not check_once(args.stop_file):
            return 0
        time.sleep(args.interval)

if __name__ == "__main__":
    raise SystemExit(main())
