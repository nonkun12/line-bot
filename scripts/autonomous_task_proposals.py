"""Generate review-only task proposals from explicitly trusted issue backlog.

Proposals never enter the executable queue automatically. An issue must be
owner-reviewed and approved through the existing reviewed catalog workflow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
TEST_PATH = re.compile(r"^(tests|uhip/tests)/test_[A-Za-z0-9_]+\.py$")
SPEC_MARKER = "<!-- autonomous-task-spec -->"


def _object(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("invalid proposal input") from exc
    if not isinstance(value, (dict, list)):
        raise ValueError("proposal input must be an object or list")
    return value


def _spec(body: str) -> dict | None:
    if not isinstance(body, str) or body.count(SPEC_MARKER) != 2:
        return None
    _, payload, _ = body.split(SPEC_MARKER)
    try:
        spec = json.loads(payload.strip())
    except ValueError:
        return None
    if not isinstance(spec, dict):
        return None
    task_id = spec.get("id")
    instruction = spec.get("instruction")
    paths = spec.get("allowed_paths")
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        return None
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 2000:
        return None
    if not isinstance(paths, list) or not paths or len(paths) > 3:
        return None
    if any(not isinstance(p, str) or not TEST_PATH.fullmatch(p) for p in paths):
        return None
    return {"id": task_id, "instruction": instruction.strip(), "allowed_paths": paths}


def build_proposals(issues_path: Path, queue_path: Path, state_path: Path, output_path: Path) -> dict:
    issues = _object(issues_path)
    queue = _object(queue_path)
    state = _object(state_path)
    if not isinstance(issues, list) or not isinstance(queue, dict) or not isinstance(state, dict):
        raise ValueError("invalid proposal input schema")
    queued = queue.get("tasks")
    completed = state.get("completed", [])
    recovery = state.get("recovery_ai")
    if not isinstance(queued, list) or not isinstance(completed, list) or not all(isinstance(x, str) for x in completed):
        raise ValueError("invalid queue or completion state")
    if not isinstance(recovery, dict) or recovery.get("schema_version") != 1 or not isinstance(recovery.get("tasks"), dict) or "checkpoint" not in recovery:
        raise ValueError("Recovery AI state is invalid")

    excluded = {x.get("id") for x in queued if isinstance(x, dict) and isinstance(x.get("id"), str)} | set(completed)
    recovery_tasks = recovery["tasks"]
    for task_id, record in recovery_tasks.items():
        if not isinstance(task_id, str) or not isinstance(record, dict):
            raise ValueError("Recovery AI task record is invalid")
        if record.get("held", False) is True or record.get("resume_requires_review", False) is True:
            excluded.add(task_id)
        elif type(record.get("held", False)) is not bool or type(record.get("resume_requires_review", False)) is not bool:
            raise ValueError("Recovery AI task flags are invalid")

    proposals = []
    seen = set()
    for issue in issues[:100]:
        if not isinstance(issue, dict):
            raise ValueError("issue record is invalid")
        labels = issue.get("labels", [])
        if not isinstance(labels, list):
            raise ValueError("issue labels are invalid")
        label_names = {label.get("name") for label in labels if isinstance(label, dict)}
        # Only explicitly tagged issue specs from the trusted backlog are considered.
        if "autonomous-task-candidate" not in label_names or issue.get("state") != "open":
            continue
        spec = _spec(issue.get("body", ""))
        if spec is None:
            continue
        if spec["id"] in excluded or spec["id"] in seen:
            continue
        number = issue.get("number")
        if type(number) is not int or number < 1:
            continue
        seen.add(spec["id"])
        proposals.append({
            **spec,
            "source_issue": number,
            "status": "REVIEW_REQUIRED",
            "proposal_fingerprint": hashlib.sha256(
                json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest(),
        })
        if len(proposals) >= 4:
            break

    result = {
        "version": 1,
        "status": "REVIEW_REQUIRED" if proposals else "NO_TRUSTED_CANDIDATES",
        "proposal_count": len(proposals),
        "proposals": proposals,
        "reason": None if proposals else "no_open_labeled_issue_with_valid_test_only_spec",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_proposals(args.issues, args.queue, args.state, args.output)
    except (ValueError, OSError) as exc:
        print("TASK_PROPOSALS_BLOCKED: " + type(exc).__name__)
        return 2
    print(json.dumps({k: result[k] for k in ("status", "proposal_count", "reason")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
