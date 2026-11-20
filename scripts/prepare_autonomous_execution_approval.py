"""Prepare a read-only, exact-task execution approval manifest.

The manifest is a convenience for a human dispatcher. It grants no authority,
does not change the catalog or queue, and cannot execute or publish code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
ALLOWED_TEST_PATH = re.compile(r"^(tests|uhip/tests)/test_[A-Za-z0-9_]+\.py$")


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("approval manifest input is missing or invalid") from exc


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def prepare_approval_manifest(
    queue: object,
    catalog: object,
    state: object,
    *,
    task_id: str,
    base_sha: str,
) -> dict[str, Any]:
    """Bind one already execution-approved catalog task to its exact run inputs."""
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise ValueError("approval manifest task ID is invalid")
    if not isinstance(base_sha, str) or not GIT_SHA.fullmatch(base_sha):
        raise ValueError("approval manifest base SHA is invalid")
    if not isinstance(queue, dict) or queue.get("max_tasks_per_run") != 1:
        raise ValueError("approval manifest queue must be capped at one task")
    queue_tasks = queue.get("tasks")
    if not isinstance(queue_tasks, list):
        raise ValueError("approval manifest queue tasks are invalid")
    selected = [row for row in queue_tasks if isinstance(row, dict) and row.get("id") == task_id]
    if len(selected) != 1:
        raise ValueError("approval manifest must select exactly one queued task")
    task = selected[0]
    if not isinstance(catalog, dict) or not isinstance(catalog.get("tasks"), list):
        raise ValueError("approval manifest catalog is invalid")
    registered = [row for row in catalog["tasks"] if isinstance(row, dict) and row.get("id") == task_id]
    if len(registered) != 1 or registered[0].get("execution_approved") is not True:
        raise ValueError("task is not independently execution-approved in the catalog")
    trusted = registered[0]
    if any(task.get(key) != trusted.get(key) for key in ("id", "instruction", "allowed_paths")):
        raise ValueError("queued task does not exactly match the approved catalog definition")
    instruction, paths = task.get("instruction"), task.get("allowed_paths")
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction.strip()) > 2000:
        raise ValueError("approval manifest instruction is invalid")
    if (
        not isinstance(paths, list) or len(paths) != 1
        or not all(isinstance(path, str) and ALLOWED_TEST_PATH.fullmatch(path) for path in paths)
    ):
        raise ValueError("approval manifest requires exactly one allowlisted test path")
    if not isinstance(state, dict) or not isinstance(state.get("completed"), list):
        raise ValueError("approval manifest durable state is invalid")
    if not all(isinstance(value, str) for value in state["completed"]):
        raise ValueError("approval manifest completion state is invalid")
    if task_id in state["completed"]:
        raise ValueError("completed task cannot be execution-approved again")
    recovery = state.get("recovery_ai")
    if (
        not isinstance(recovery, dict)
        or type(recovery.get("schema_version")) is not int
        or recovery.get("schema_version") != 1
        or not isinstance(recovery.get("tasks"), dict)
    ):
        raise ValueError("approval manifest Recovery AI state is invalid")
    recovery_row = recovery["tasks"].get(task_id, {})
    if not isinstance(recovery_row, dict):
        raise ValueError("approval manifest Recovery AI task state is invalid")
    held, review = recovery_row.get("held", False), recovery_row.get("resume_requires_review", False)
    if type(held) is not bool or type(review) is not bool:
        raise ValueError("approval manifest Recovery AI flags are invalid")
    if held or review:
        raise ValueError("HOLD or review-required task cannot be approved for execution")

    normalized_instruction = instruction.strip()[:2000]
    canonical_paths = sorted(paths)
    return {
        "schema_version": 1,
        "status": "READY_FOR_HUMAN_DISPATCH",
        "task_id": task_id,
        "base_sha": base_sha,
        "instruction_sha256": _sha256(normalized_instruction),
        "allowed_paths_sha256": _sha256(
            json.dumps(canonical_paths, ensure_ascii=False, separators=(",", ":"))
        ),
        "allowed_paths": canonical_paths,
        "max_tasks": 1,
        "execution_approval_input": "APPROVE_EXECUTION",
        "execution_authorized": False,
        "human_dispatch_required": True,
        "merge_authorized": False,
        "deploy_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = prepare_approval_manifest(
            _read(args.queue), _read(args.catalog), _read(args.state),
            task_id=args.task_id, base_sha=args.base_sha,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = args.output.with_name(args.output.name + ".tmp")
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(args.output)
    except (OSError, ValueError) as exc:
        print(f"EXECUTION_APPROVAL_MANIFEST_BLOCKED: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
