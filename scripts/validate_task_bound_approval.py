"""Validate a one-run, task-bound approval without mutating tracked state."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ApprovalError(ValueError):
    """Raised when a one-time task approval cannot be verified."""


def _load_tasks(document: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get("tasks"), list):
        raise ApprovalError(f"{label}_tasks_invalid")
    tasks = document["tasks"]
    if any(not isinstance(item, dict) for item in tasks):
        raise ApprovalError(f"{label}_task_invalid")
    ids = [item.get("id") for item in tasks]
    if any(not isinstance(task_id, str) or not task_id for task_id in ids):
        raise ApprovalError(f"{label}_task_id_invalid")
    if len(ids) != len(set(ids)):
        raise ApprovalError(f"{label}_duplicate_task_id")
    return tasks


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def allowed_paths_digest(paths: Any) -> str:
    if (not isinstance(paths, list) or not paths
            or any(not isinstance(path, str) or not path for path in paths)
            or len(paths) != len(set(paths))):
        raise ApprovalError("allowed_paths_invalid")
    canonical = json.dumps(sorted(paths), ensure_ascii=False, separators=(",", ":"))
    return _sha256_text(canonical)


def build_one_time_approval_catalog(
    *,
    queue: Any,
    catalog: Any,
    state: Any,
    approval: str,
    task_id: str,
    allowed_paths_sha256: str,
    instruction_sha256: str,
    approval_base_sha: str,
    current_base_sha: str,
) -> dict[str, Any]:
    """Return an ephemeral catalog authorizing exactly one eligible queued task."""
    if approval != "APPROVE_EXECUTION":
        raise ApprovalError("explicit_execution_approval_missing")
    if not isinstance(task_id, str) or not task_id or len(task_id) > 100:
        raise ApprovalError("approval_task_id_invalid")
    if not _SHA256_RE.fullmatch(allowed_paths_sha256 or ""):
        raise ApprovalError("approval_allowed_paths_sha256_invalid")
    if not _SHA256_RE.fullmatch(instruction_sha256 or ""):
        raise ApprovalError("approval_instruction_sha256_invalid")
    if not _GIT_SHA_RE.fullmatch(approval_base_sha or ""):
        raise ApprovalError("approval_base_sha_invalid")
    if not _GIT_SHA_RE.fullmatch(current_base_sha or "") or approval_base_sha != current_base_sha:
        raise ApprovalError("approval_base_sha_mismatch")

    queued = _load_tasks(queue, "queue")
    registered = _load_tasks(catalog, "catalog")
    queue_matches = [item for item in queued if item.get("id") == task_id]
    catalog_matches = [item for item in registered if item.get("id") == task_id]
    if len(queue_matches) != 1 or len(catalog_matches) != 1:
        raise ApprovalError("approval_task_not_queued_and_registered")
    queued_task, registered_task = queue_matches[0], catalog_matches[0]
    for key in ("id", "instruction", "allowed_paths"):
        if queued_task.get(key) != registered_task.get(key):
            raise ApprovalError("approval_task_definition_mismatch")
    instruction = registered_task.get("instruction")
    if not isinstance(instruction, str) or _sha256_text(instruction) != instruction_sha256:
        raise ApprovalError("approval_instruction_sha256_mismatch")
    if allowed_paths_digest(registered_task.get("allowed_paths")) != allowed_paths_sha256:
        raise ApprovalError("approval_allowed_paths_sha256_mismatch")

    if not isinstance(state, dict) or not isinstance(state.get("completed", []), list):
        raise ApprovalError("approval_durable_state_invalid")
    recovery = state.get("recovery_ai", {})
    if not isinstance(recovery, dict) or not isinstance(recovery.get("tasks", {}), dict):
        raise ApprovalError("approval_recovery_state_invalid")
    if task_id in state.get("completed", []):
        raise ApprovalError("approval_task_already_completed")
    recovery_record = recovery.get("tasks", {}).get(task_id, {})
    if not isinstance(recovery_record, dict):
        raise ApprovalError("approval_recovery_record_invalid")
    if recovery_record.get("held") is True:
        raise ApprovalError("approval_task_held")
    if recovery_record.get("resume_requires_review") is True:
        raise ApprovalError("approval_task_requires_review")

    result = json.loads(json.dumps(catalog, ensure_ascii=False))
    for item in result["tasks"]:
        item["execution_approved"] = item.get("id") == task_id
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--allowed-paths-sha256", required=True)
    parser.add_argument("--instruction-sha256", required=True)
    parser.add_argument("--approval-base-sha", required=True)
    parser.add_argument("--current-base-sha", required=True)
    args = parser.parse_args()
    try:
        result = build_one_time_approval_catalog(
            queue=json.loads(args.queue.read_text(encoding="utf-8")),
            catalog=json.loads(args.catalog.read_text(encoding="utf-8")),
            state=json.loads(args.state.read_text(encoding="utf-8")),
            approval=args.approval,
            task_id=args.task_id,
            allowed_paths_sha256=args.allowed_paths_sha256,
            instruction_sha256=args.instruction_sha256,
            approval_base_sha=args.approval_base_sha,
            current_base_sha=args.current_base_sha,
        )
    except (OSError, json.JSONDecodeError, ApprovalError) as exc:
        raise SystemExit(f"task_bound_approval_blocked:{type(exc).__name__}:{exc}") from exc
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print(f"ONE_TIME_APPROVAL=PASS task_id={args.task_id} scope=single_task")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
