"""Safely resume exactly one held queue task after explicit cause-fixed confirmation."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from scripts.recovery_ai import RecoveryStateError, RecoveryStore, _safe_id


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"state unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"state must be an object: {path.name}")
    return value


def _atomic_json_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temp_name = handle.name
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def resume_task(
    *,
    state_path: Path,
    recovery_path: Path,
    queue_path: Path,
    task_id: str,
    cause_fixed: bool,
    catalog_path: Path | None = None,
) -> dict:
    """Unhold one pending task only when cause-fixed confirmation is explicit.

    A held catalog-only task may have been removed from the runtime queue. Permit
    an exact-one-match lookup in the reviewed catalog, while retaining explicit
    cause-fixed confirmation and the post-resume review gate.
    """
    task_id = _safe_id(task_id)
    if cause_fixed is not True:
        raise ValueError("explicit confirmation that the cause is fixed is required")

    state = _read_json(state_path)
    if state.get("version") != 1 or not isinstance(state.get("completed"), list):
        raise ValueError("durable loop state is invalid")

    queue = _read_json(queue_path)
    tasks = queue.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("task queue is invalid")
    matches = [
        task for task in tasks
        if isinstance(task, dict) and task.get("id") == task_id
    ]
    if not matches and catalog_path is not None:
        catalog_tasks = _read_json(catalog_path).get("tasks")
        if not isinstance(catalog_tasks, list):
            raise ValueError("task catalog is invalid")
        matches = [
            task for task in catalog_tasks
            if isinstance(task, dict) and task.get("id") == task_id
        ]
    if len(matches) != 1:
        raise ValueError("task ID must match exactly one queued task")
    if task_id in state["completed"]:
        raise ValueError("completed tasks cannot be resumed")

    recovery = _read_json(recovery_path)
    if (
        recovery.get("schema_version") != 1
        or not isinstance(recovery.get("tasks"), dict)
        or "checkpoint" not in recovery
    ):
        raise ValueError("Recovery AI state is invalid")
    if state.get("recovery_ai") != recovery:
        raise ValueError("durable and local Recovery AI state mismatch")

    try:
        store = RecoveryStore(recovery_path)
        before = store.task_status(task_id)
        if before.get("held") is not True:
            raise ValueError("task is not held")
        store.resume_held_task(task_id, cause_fixed=True)
        updated = _read_json(recovery_path)
        after = RecoveryStore(recovery_path).task_status(task_id)
    except RecoveryStateError as exc:
        raise ValueError("Recovery AI state could not be trusted or persisted") from exc

    if after.get("held") is not False or after.get("resume_requires_review") is not True:
        raise ValueError("resume verification failed; refusing to continue")
    state["recovery_ai"] = updated
    _atomic_json_write(state_path, state)
    return {"task_id": task_id, "held": False, "resume_requires_review": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--recovery-state", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--cause-fixed", action="store_true")
    args = parser.parse_args()
    result = resume_task(
        state_path=args.state,
        recovery_path=args.recovery_state,
        queue_path=args.queue,
        task_id=args.task_id,
        cause_fixed=args.cause_fixed,
        catalog_path=args.catalog,
    )
    print(
        "RESUME_APPROVED "
        f"task_id={result['task_id']} "
        f"held={str(result['held']).lower()} "
        f"resume_requires_review={str(result['resume_requires_review']).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
