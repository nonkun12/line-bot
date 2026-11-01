"""Register one human-reviewed, test-only candidate into the immutable task catalog.

This command only edits the catalog on a dedicated review branch. It never
approves an issue, changes durable state, or dispatches a task.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SPEC_MARKER = "<!-- autonomous-task-spec -->"
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
TEST_PATH = re.compile(r"^tests/test_[A-Za-z0-9_]+\.py$")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("invalid registration input") from exc


def parse_candidate_issue(issue: dict[str, Any], confirmation: str) -> dict[str, Any]:
    number = issue.get("number")
    if type(number) is not int or number < 1 or confirmation != str(number):
        raise ValueError("issue confirmation does not match")
    if issue.get("state") != "open":
        raise ValueError("candidate issue must be open")
    labels = issue.get("labels")
    if not isinstance(labels, list) or not all(isinstance(x, dict) for x in labels):
        raise ValueError("candidate issue labels are invalid")
    names = {x.get("name") for x in labels}
    if "autonomous-task-candidate" not in names or "autonomous-task-approved" in names:
        raise ValueError("issue must be candidate-only; approval is a separate action")

    body = issue.get("body")
    if not isinstance(body, str) or body.count(SPEC_MARKER) != 2:
        raise ValueError("candidate spec markers are invalid")
    _, raw_spec, _ = body.split(SPEC_MARKER)
    try:
        spec = json.loads(raw_spec.strip())
    except ValueError as exc:
        raise ValueError("candidate spec JSON is invalid") from exc
    if not isinstance(spec, dict) or set(spec) != {"id", "instruction", "allowed_paths"}:
        raise ValueError("candidate spec fields are invalid")

    task_id = spec["id"]
    instruction = spec["instruction"]
    paths = spec["allowed_paths"]
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise ValueError("candidate task ID is invalid")
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 2000:
        raise ValueError("candidate instruction is invalid")
    if not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], str):
        raise ValueError("exactly one test file must be allowlisted")
    if not TEST_PATH.fullmatch(paths[0]):
        raise ValueError("candidate path is not an allowlisted test file")
    lowered = instruction.lower()
    if not any(word in lowered for word in ("test", "テスト", "回帰")):
        raise ValueError("candidate instruction must describe a test task")
    return {
        "id": task_id,
        "instruction": instruction.strip(),
        "allowed_paths": paths,
    }


def register_candidate(
    issue: dict[str, Any],
    catalog: dict[str, Any],
    durable_state: dict[str, Any],
    runtime_queue: dict[str, Any],
    confirmation: str,
) -> dict[str, Any]:
    if not isinstance(catalog, dict) or not isinstance(catalog.get("tasks"), list):
        raise ValueError("task catalog is invalid")
    if not isinstance(durable_state, dict) or not isinstance(durable_state.get("completed"), list):
        raise ValueError("durable completion state is invalid")
    recovery = durable_state.get("recovery_ai")
    if (
        not isinstance(recovery, dict)
        or recovery.get("schema_version") != 1
        or not isinstance(recovery.get("tasks"), dict)
        or "checkpoint" not in recovery
    ):
        raise ValueError("durable Recovery AI state is invalid")
    if not isinstance(runtime_queue, dict) or not isinstance(runtime_queue.get("tasks"), list):
        raise ValueError("runtime queue is invalid")

    spec = parse_candidate_issue(issue, confirmation)
    task_id = spec["id"]
    existing_ids = set()
    for entry in catalog["tasks"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ValueError("catalog task entry is invalid")
        existing_ids.add(entry["id"])
    if task_id in existing_ids:
        raise ValueError("task ID is already registered")
    if task_id in durable_state["completed"]:
        raise ValueError("task ID is already completed")
    if any(isinstance(row, dict) and row.get("id") == task_id for row in runtime_queue["tasks"]):
        raise ValueError("task ID is already queued")
    if task_id in recovery["tasks"]:
        raise ValueError("task ID already has Recovery AI state")

    updated = dict(catalog)
    updated["tasks"] = [*catalog["tasks"], spec]
    return updated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--confirm-issue", required=True)
    args = parser.parse_args()
    try:
        issue = _read_json(args.issue)
        catalog = _read_json(args.catalog)
        state = _read_json(args.state)
        queue = _read_json(args.queue)
        updated = register_candidate(issue, catalog, state, queue, args.confirm_issue)
        args.catalog.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError) as exc:
        print("TASK_REGISTRATION_BLOCKED: " + str(exc))
        return 2
    print(json.dumps({"status": "REGISTRATION_PR_READY", "task_id": updated["tasks"][-1]["id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
