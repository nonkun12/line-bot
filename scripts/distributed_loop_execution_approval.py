"""Fail-closed, one-task approval gate for the distributed autonomous loop."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def authorize_one_task(
    queue_path: Path,
    event_path: Path,
    *,
    base_sha: str,
    ref: str,
    actor: str,
    repository: str,
) -> dict[str, Any]:
    """Validate the signed-by-context dispatch intent and reduce queue to one exact task."""
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    event = json.loads(event_path.read_text(encoding="utf-8"))
    if not isinstance(queue, dict) or not isinstance(event, dict):
        raise ValueError("approval_input_invalid")
    inputs = event.get("inputs")
    sender, repo = event.get("sender"), event.get("repository")
    if not isinstance(inputs, dict) or not isinstance(sender, dict) or not isinstance(repo, dict):
        raise ValueError("approval_event_context_missing")
    if (
        os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or actor != "nonkun12"
        or sender.get("login") != actor
        or ref != "refs/heads/main"
        or repository != "nonkun12/line-bot"
        or repo.get("full_name") != repository
        or inputs.get("execution_approval") != "APPROVE_EXECUTION"
        or inputs.get("mode", "normal") != "normal"
    ):
        raise ValueError("approval_event_not_authorized")
    if not GIT_SHA.fullmatch(base_sha):
        raise ValueError("approval_base_sha_invalid")
    if inputs.get("approval_base_sha") != base_sha:
        raise ValueError("approval_base_sha_mismatch")
    tasks = queue.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("approved_runtime_queue_empty")
    task_id = inputs.get("approval_task_id")
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise ValueError("approval_task_id_invalid")
    matches = [task for task in tasks if isinstance(task, dict) and task.get("id") == task_id]
    if len(matches) != 1 or len(tasks) != 1:
        raise ValueError("approval_must_bind_exactly_one_queued_task")
    task = matches[0]
    instruction, paths = task.get("instruction"), task.get("allowed_paths")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("approved_instruction_invalid")
    if (
        not isinstance(paths, list) or not paths
        or not all(isinstance(path, str) and path and path == path.strip() for path in paths)
        or len(set(paths)) != len(paths)
    ):
        raise ValueError("approved_paths_invalid")
    instruction_digest = _digest(instruction)
    paths_digest = _digest(json.dumps(sorted(paths), ensure_ascii=False, separators=(",", ":")))
    if not SHA256.fullmatch(str(inputs.get("approval_instruction_sha256", ""))) or inputs["approval_instruction_sha256"] != instruction_digest:
        raise ValueError("approval_instruction_digest_mismatch")
    if not SHA256.fullmatch(str(inputs.get("approval_allowed_paths_sha256", ""))) or inputs["approval_allowed_paths_sha256"] != paths_digest:
        raise ValueError("approval_allowed_paths_digest_mismatch")
    if queue.get("max_tasks_per_run") != 1:
        raise ValueError("approval_task_limit_must_be_one")
    queue["tasks"] = [task]
    queue["max_tasks_per_run"] = 1
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "PASS", "task_id": task_id, "base_sha": base_sha,
        "instruction_sha256": instruction_digest, "allowed_paths_sha256": paths_digest,
        "authorized_task_count": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    try:
        result = authorize_one_task(
            args.queue, args.event, base_sha=args.base_sha,
            ref=os.environ.get("GITHUB_REF", ""),
            actor=os.environ.get("GITHUB_ACTOR", ""),
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"EXECUTION_APPROVAL=BLOCKED reason={type(exc).__name__}:{exc}")
        return 1
    print("EXECUTION_APPROVAL=" + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
