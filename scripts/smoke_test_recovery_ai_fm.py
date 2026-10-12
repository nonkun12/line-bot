"""Mac-only smoke test for the Recovery AI -> local Apple Foundation Models path.

Run from the repository root on a Mac with the `fm` CLI available:
    python3 scripts/smoke_test_recovery_ai_fm.py

Uses a temporary directory and synthetic failure metadata only. It never reads or
writes the live task queue, applies patches, resumes tasks, merges, or deploys.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from scripts.recovery_ai import RecoveryStore
from scripts.recovery_ai_loop_adapter import record_loop_outcome


def main() -> int:
    previous_opt_in = os.environ.get("RECOVERY_AI_APPLE_ADVISOR")
    os.environ["RECOVERY_AI_APPLE_ADVISOR"] = "1"
    try:
        with tempfile.TemporaryDirectory(prefix="recovery-ai-fm-smoke-") as tmp:
            state_path = Path(tmp) / "recovery-ai-state.json"
            synthetic_result = {
                "task_id": "fm-smoke-test",
                "status": "FAIL",
                "exit_code": 1,
                "failure_reason": "network_transient",
            }
            outcome = record_loop_outcome(state_path, synthetic_result)
            state = RecoveryStore(state_path)._read()
            task_state = state["tasks"].get("fm-smoke-test", {})
            advisor = outcome.get("apple_advisor", {})
            decision = outcome.get("decision", {})

            checks = {
                "temporary_state_created": state_path.is_file(),
                "failure_state_read_back": task_state.get("consecutive_failures") == 1,
                "category_read_back": task_state.get("last_category") == "network_transient",
                "deterministic_decision_is_retry": decision.get("action") == "RETRY",
                "advisor_was_invoked": advisor.get("reason") != "advisor_not_enabled",
                "fm_advice_returned": advisor.get("available") is True,
            }
            print(json.dumps({
                "checks": checks,
                "advisor_reason": advisor.get("reason", "missing"),
                "decision_action": decision.get("action", "missing"),
                "live_queue_touched": False,
                "patch_or_deploy_performed": False,
            }, ensure_ascii=False, sort_keys=True))
            if not all(checks.values()):
                return 2
            return 0
    finally:
        if previous_opt_in is None:
            os.environ.pop("RECOVERY_AI_APPLE_ADVISOR", None)
        else:
            os.environ["RECOVERY_AI_APPLE_ADVISOR"] = previous_opt_in


if __name__ == "__main__":
    raise SystemExit(main())
