"""Read-only Mac entrypoint for diagnosing an existing Recovery AI incident.

Accepts either a standalone RecoveryStore JSON file or the durable
.autonomous-loop-state.json envelope. Never writes state or executes advice.
"""
from __future__ import annotations

import argparse
import json
import re
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


class ReadOnlyRecoveryStore(RecoveryStore):
    """RecoveryStore-compatible view over validated in-memory state."""

    def __init__(self, data: dict):
        super().__init__(Path("<read-only-recovery-state>"))
        self._data = data

    def _read(self) -> dict:
        return self._data


def _extract_recovery_state(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise RecoveryStateError("recovery state schema invalid")
    data = payload.get("recovery_ai", payload)
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or not isinstance(data.get("tasks"), dict)
        or "checkpoint" not in data
    ):
        raise RecoveryStateError("recovery state schema invalid")
    return data


def load_readonly_store(state_file: str | Path) -> RecoveryStore:
    """Read an existing file, accepting the standalone or durable envelope schema."""
    path = Path(state_file)
    if not path.exists() or not path.is_file():
        raise RecoveryStateError("recovery state file missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryStateError("recovery state unreadable") from exc
    return ReadOnlyRecoveryStore(_extract_recovery_state(payload))


def diagnose_existing_incident(store: RecoveryStore, task_id: str, *, advisor=diagnose) -> dict:
    """Read existing state and optionally produce advice without writing state."""
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", task_id):
        raise ValueError("invalid task ID")
    record = store.task_status(task_id)
    category = record.get("last_category")
    fingerprint = record.get("last_fingerprint")
    failures = record.get("consecutive_failures")
    attempts = record.get("same_fingerprint_attempts")
    updated_at = record.get("updated_at")

    def skipped(reason: str) -> dict:
        return {"status": "SKIPPED", "task_id": task_id, "reason": reason,
                "updated_at": updated_at, "state_mutated": False}

    if not record or not isinstance(fingerprint, str) or not fingerprint:
        return skipped("no_existing_incident")
    if record.get("held") is True or not isinstance(failures, int) or failures >= HOLD_AFTER_FAILURES:
        return skipped("incident_held_or_failure_limit")
    if category not in REPAIRABLE_CATEGORIES:
        return skipped("category_not_allowlisted")
    if not isinstance(attempts, int) or attempts != 1:
        return skipped("repair_budget_not_available")

    decision = RecoveryDecision(
        action="REPAIR_ONCE",
        reason="existing_record_allows_advisory_only_diagnosis",
        task_id=task_id,
        fingerprint=fingerprint,
        consecutive_failures=failures,
    )
    result = advise_for_decision(decision, category, (), advisor=advisor)
    return {
        "status": result.status, "task_id": task_id,
        "decision_action": result.decision_action, "suggestion": result.suggestion,
        "reason": result.reason, "updated_at": updated_at, "state_mutated": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read an existing Recovery AI incident and request advisory-only local diagnosis."
    )
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args(argv)
    try:
        store = load_readonly_store(args.state_file)
        result = diagnose_existing_incident(store, args.task_id)
    except (RecoveryStateError, ValueError, OSError) as exc:
        print(json.dumps({"status": "ERROR", "reason": type(exc).__name__,
                          "state_mutated": False}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"ADVISORY_ONLY", "SKIPPED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
