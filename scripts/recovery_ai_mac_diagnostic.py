"""Read-only Mac entrypoint for diagnosing an already-recorded Recovery AI incident.

This command never records a failure or changes recovery state. It may ask the
local fm advisor for suggestions only when the existing deterministic state
shows a single allowed repair opportunity. Suggestions remain advisory only.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from scripts.recovery_ai import (
    HOLD_AFTER_FAILURES,
    REPAIRABLE_CATEGORIES,
    RecoveryDecision,
    RecoveryStateError,
    RecoveryStore,
)
from scripts.recovery_ai_local_advisor import advise_for_decision
from scripts.recovery_ai_fm_advisor import diagnose


def diagnose_existing_incident(store: RecoveryStore, task_id: str, *, advisor=diagnose) -> dict:
    """Read existing state and optionally produce advice without writing state."""
    record = store.task_status(task_id)  # read-only; deliberately no record_failure()
    category = record.get("last_category")
    fingerprint = record.get("last_fingerprint")
    failures = record.get("consecutive_failures")
    attempts = record.get("same_fingerprint_attempts")

    if not record or not isinstance(fingerprint, str) or not fingerprint:
        return {"status": "SKIPPED", "task_id": task_id, "reason": "no_existing_incident"}

    if record.get("held") is True or not isinstance(failures, int) or failures >= HOLD_AFTER_FAILURES:
        return {"status": "SKIPPED", "task_id": task_id, "reason": "incident_held_or_failure_limit"}

    if category not in REPAIRABLE_CATEGORIES:
        return {"status": "SKIPPED", "task_id": task_id, "reason": "category_not_allowlisted"}

    # Existing state only; this mirrors the one-attempt budget without consuming it.
    if not isinstance(attempts, int) or attempts != 1:
        return {"status": "SKIPPED", "task_id": task_id, "reason": "repair_budget_not_available"}

    decision = RecoveryDecision(
        action="REPAIR_ONCE",
        reason="existing_record_allows_advisory_only_diagnosis",
        task_id=task_id,
        fingerprint=fingerprint,
        consecutive_failures=failures,
    )
    result = advise_for_decision(decision, category, (), advisor=advisor)
    return {"status": result.status, "task_id": task_id,
            "decision_action": result.decision_action, "suggestion": result.suggestion,
            "reason": result.reason, "state_mutated": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read an existing Recovery AI incident and request advisory-only local diagnosis."
    )
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = diagnose_existing_incident(RecoveryStore(Path(args.state_file)), args.task_id)
    except (RecoveryStateError, ValueError) as exc:
        # Do not print raw state contents or exception details.
        print(json.dumps({"status": "ERROR", "reason": type(exc).__name__,
                          "state_mutated": False}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"ADVISORY_ONLY", "SKIPPED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
