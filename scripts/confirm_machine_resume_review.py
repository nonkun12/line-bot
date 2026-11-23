"""Confirm a pending resume only after task-bound, same-run machine REA evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import Any

from scripts.confirm_recovery_resume_review import confirm_in_durable_state
from scripts.machine_resume_evidence import validate_machine_resume_evidence


def _read_object(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("resume_input_unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError("resume_input_schema_invalid")
    return value


def confirm_if_machine_verified(
    *,
    state_file: str | Path,
    recovery_state_file: str | Path,
    catalog_file: str | Path,
    evidence_file: str | Path,
    task_id: str,
    expected_base_sha: str,
    expected_workflow_run_id: str,
    expected_run_attempt: int,
    expected_nonce: str,
    validation_now: datetime | None = None,
) -> dict[str, Any]:
    """Clear only the pending review bit for one already-unheld eligible task."""
    if not isinstance(task_id, str) or not task_id or len(task_id) > 100:
        raise ValueError("resume_task_id_invalid")
    catalog = _read_object(catalog_file)
    specs = catalog.get("tasks")
    if not isinstance(specs, list):
        raise ValueError("resume_catalog_invalid")
    matches = [
        item for item in specs
        if isinstance(item, dict) and item.get("id") == task_id
    ]
    if len(matches) != 1:
        raise ValueError("resume_catalog_task_not_unique")
    task = matches[0]
    # Check durable HOLD/review state before inspecting evidence so stale or
    # malformed evidence can never obscure the stronger safety decision.
    durable = _read_object(state_file)
    recovery = durable.get("recovery_ai")
    if (
        not isinstance(recovery, dict)
        or recovery.get("schema_version") != 1
        or not isinstance(recovery.get("tasks"), dict)
    ):
        raise ValueError("resume_recovery_state_invalid")
    record = recovery["tasks"].get(task_id)
    if (
        not isinstance(record, dict)
        or record.get("held") is not False
        or record.get("resume_requires_review") is not True
    ):
        raise ValueError("resume_task_not_pending_machine_review")

    evidence = _read_object(evidence_file)
    result = validate_machine_resume_evidence(
        task,
        evidence,
        expected_base_sha=expected_base_sha,
        expected_workflow_run_id=expected_workflow_run_id,
        expected_run_attempt=expected_run_attempt,
        expected_nonce=expected_nonce,
        now=validation_now,
    )
    if result.get("eligible") is not True:
        raise ValueError(str(result.get("reason_code", "resume_evidence_blocked")))

    # The existing durable writer performs atomic replacement and read-back.
    # It is reached only after all task and evidence bindings have passed.
    confirm_in_durable_state(state_file, task_id, recovery_state_file)
    return {
        "status": "PASS",
        "task_id": task_id,
        "evidence_nonce": result["nonce"],
        "workflow_run_id": result["workflow_run_id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--recovery-state-file", required=True)
    parser.add_argument("--catalog-file", required=True)
    parser.add_argument("--evidence-file", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--expected-nonce", required=True)
    args = parser.parse_args()
    try:
        result = confirm_if_machine_verified(
            state_file=args.state_file,
            recovery_state_file=args.recovery_state_file,
            catalog_file=args.catalog_file,
            evidence_file=args.evidence_file,
            task_id=args.task_id,
            expected_base_sha=args.base_sha,
            expected_workflow_run_id=args.workflow_run_id,
            expected_run_attempt=args.run_attempt,
            expected_nonce=args.expected_nonce,
        )
    except (ValueError, OSError) as exc:
        print(f"MACHINE_RESUME_BLOCKED: {type(exc).__name__}:{exc}")
        return 1
    print(
        "MACHINE_RESUME_CONFIRMED "
        f"task_id={result['task_id']} "
        f"workflow_run_id={result['workflow_run_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
