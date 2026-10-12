"""Mac-only smoke test for Recovery AI fast-path and local Apple Foundation Models.

Run from the repository root on a Mac with the `fm` CLI available:
    python3 scripts/smoke_test_recovery_ai_fm.py

Uses temporary state and synthetic failures only. It never touches the live queue,
applies patches, resumes tasks, merges, or deploys.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.recovery_ai import RecoveryStore
from scripts.recovery_ai_loop_adapter import record_loop_outcome


def main() -> int:
    previous_opt_in = os.environ.get("RECOVERY_AI_APPLE_ADVISOR")
    os.environ["RECOVERY_AI_APPLE_ADVISOR"] = "1"
    try:
        with tempfile.TemporaryDirectory(prefix="recovery-ai-fm-smoke-") as tmp:
            root = Path(tmp)

            # Routine transient errors should retry immediately without waiting for fm.
            retry_path = root / "retry-state.json"
            retry_started = time.perf_counter()
            retry = record_loop_outcome(retry_path, {
                "task_id": "fm-smoke-retry",
                "status": "FAIL",
                "exit_code": 1,
                "failure_reason": "network_transient",
            })
            retry_elapsed_ms = round((time.perf_counter() - retry_started) * 1000, 2)
            retry_state = RecoveryStore(retry_path).task_status("fm-smoke-retry")
            retry_advisor = retry.get("apple_advisor", {})

            # Repair-worthy failures may ask fm for diagnostic advice after durable state.
            repair_path = root / "repair-state.json"
            repair_started = time.perf_counter()
            repair = record_loop_outcome(repair_path, {
                "task_id": "fm-smoke-repair",
                "status": "TIMEOUT",
                "exit_code": 1,
                "failure_reason": "task_timeout",
            })
            repair_elapsed_ms = round((time.perf_counter() - repair_started) * 1000, 2)
            repair_state = RecoveryStore(repair_path).task_status("fm-smoke-repair")
            advisor = repair.get("apple_advisor", {})

            checks = {
                "temporary_state_created": retry_path.is_file() and repair_path.is_file(),
                "retry_failure_state_read_back": retry_state.get("last_category") == "network_transient",
                "transient_decision_is_retry": retry.get("decision", {}).get("action") == "RETRY",
                "retry_skips_advisor": retry_advisor.get("reason") == "fast_path_no_advice_needed",
                "repair_state_read_back": repair_state.get("last_category") == "timeout",
                "repair_decision_is_bounded": repair.get("decision", {}).get("action") == "REPAIR_ONCE",
                "advisor_was_invoked": advisor.get("reason") != "advisor_not_enabled",
                "fm_advice_returned": advisor.get("available") is True,
            }
            print(json.dumps({
                "checks": checks,
                "advisor_reason": advisor.get("reason", "missing"),
                "retry_fast_path_elapsed_ms": retry_elapsed_ms,
                "repair_with_advisor_elapsed_ms": repair_elapsed_ms,
                "retry_action": retry.get("decision", {}).get("action", "missing"),
                "repair_action": repair.get("decision", {}).get("action", "missing"),
                "live_queue_touched": False,
                "patch_or_deploy_performed": False,
            }, ensure_ascii=False, sort_keys=True))
            return 0 if all(checks.values()) else 2
    finally:
        if previous_opt_in is None:
            os.environ.pop("RECOVERY_AI_APPLE_ADVISOR", None)
        else:
            os.environ["RECOVERY_AI_APPLE_ADVISOR"] = previous_opt_in


if __name__ == "__main__":
    raise SystemExit(main())
