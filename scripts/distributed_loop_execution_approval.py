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
MAX_INSTRUCTION_LENGTH = 2000


def _normalize_instruction(value: str) -> str:
    return value.strip()[:MAX_INSTRUCTION_LENGTH]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def authorize_one_task(
    queue_path: Path,
    event_path: Path,
    catalog_path: Path,
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
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_tasks = catalog.get("tasks") if isinstance(catalog, dict) else None
    if not isinstance(catalog_tasks, list):
        raise ValueError("approval_catalog_invalid")
    tasks = queue.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("approved_runtime_queue_empty")
    task_id = inputs.get("approval_task_id")
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise ValueError("approval_task_id_invalid")
    matches = [task for task in tasks if isinstance(task, dict) and task.get("id") == task_id]
    if len(matches) != 1:
        raise ValueError("approval_must_bind_exactly_one_queued_task")
    task = matches[0]
    registered = [item for item in catalog_tasks if isinstance(item, dict) and item.get("id") == task_id]
    if len(registered) != 1 or registered[0].get("execution_approved") is not True:
        raise ValueError("approval_task_not_registered_or_not_approved")
    if any(task.get(key) != registered[0].get(key) for key in ("id", "instruction", "allowed_paths")):
        raise ValueError("approval_task_definition_mismatch")
    instruction, paths = task.get("instruction"), task.get("allowed_paths")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("approved_instruction_invalid")
    if (
        not isinstance(paths, list) or not paths
        or not all(isinstance(path, str) and path and path == path.strip() for path in paths)
        or len(set(paths)) != len(paths)
    ):
        raise ValueError("approved_paths_invalid")
    instruction_digest = _digest(_normalize_instruction(instruction))
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
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    try:
        result = authorize_one_task(
            args.queue, args.event, args.catalog, base_sha=args.base_sha,
            ref=os.environ.get("GITHUB_REF", ""),
            actor=os.environ.get("GITHUB_ACTOR", ""),
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"EXECUTION_APPROVAL=BLOCKED reason={type(exc).__name__}:{exc}")
        return 1
    os.environ["AUTONOMOUS_TASK_ID"] = str(result["task_id"])
    task_rows = json.loads(args.queue.read_text(encoding="utf-8"))["tasks"]
    os.environ["AUTONOMOUS_ALLOWED_PATHS"] = json.dumps(task_rows[0]["allowed_paths"], ensure_ascii=False)
    try:
        # Verify the exact dispatch context here, but do not consume the one-shot
        # marker. run_guarded_runtime owns the single atomic consumption immediately
        # before execution; consuming here would make the runtime reject the same
        # valid approval as already consumed.
        from scripts.run_guarded_runtime import _verify_execution_approval
        evidence = _verify_execution_approval(args.base_sha, task_rows[0]["instruction"])
        if evidence.get("execution_authorized") is not True:
            raise ValueError("independent_execution_approval_verification_failed")
    except Exception as exc:
        print(f"EXECUTION_APPROVAL=BLOCKED reason={type(exc).__name__}")
        return 1
    result["verification"] = "PASS"
    result["consumption"] = "DEFERRED_TO_GUARDED_RUNTIME"
    resume_task_id = os.environ.get("RESUME_TASK_ID", "").strip()
    if resume_task_id and resume_task_id != str(result["task_id"]):
        print("EXECUTION_APPROVAL=BLOCKED reason=resume_task_id_mismatch")
        return 1
    output_path = os.environ.get("GITHUB_OUTPUT", "")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            output.write("task_id=" + str(result["task_id"]) + "\n")
    print("EXECUTION_APPROVAL=" + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
