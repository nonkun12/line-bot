"""One-command, isolated macOS smoke test for Recovery AI + Apple local advisor.

This only writes a temporary state file and uses synthetic failure metadata. It
never touches the live task queue, runs repairs, or changes deployment settings.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from scripts.recovery_ai_local import record_failure_with_local_advice
from scripts.recovery_ai import RecoveryStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--enable-advisor",
        action="store_true",
        help="explicitly call Apple's local fm advisor; without this flag no model is called",
    )
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="recovery-ai-smoke-") as directory:
        state_path = Path(directory) / "state.json"
        store = RecoveryStore(state_path)
        result = record_failure_with_local_advice(
            store,
            "mac-smoke-test",
            "timeout",
            ["tests/synthetic_smoke_test.py"],
            advisor_enabled=args.enable_advisor,
        )
        read_back = store.task_status("mac-smoke-test")
        persisted = (
            state_path.is_file()
            and read_back.get("consecutive_failures") == 1
            and read_back.get("last_category") == "timeout"
        )
        report = {
            "test": "recovery_ai_mac_smoke",
            "state_persisted_and_read_back": persisted,
            "decision_action": result.decision.action,
            "decision_reason": result.decision.reason,
            "advisor_requested": args.enable_advisor,
            "advisor_available": result.advisor.available,
            "advisor_reason": result.advisor.reason,
            "advice": result.advisor.advice if result.advisor.available else "",
            "live_queue_touched": False,
            "patch_or_deploy_performed": False,
        }
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        if not persisted:
            return 1
        if args.enable_advisor and not result.advisor.available:
            return 2
        if result.decision.action != "REPAIR_ONCE":
            return 3
        return 0


if __name__ == "__main__":
    sys.exit(main())
