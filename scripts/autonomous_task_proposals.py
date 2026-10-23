"""Generate reviewed task proposals and queue only explicitly approved issues.

Candidate-only issues remain review-only. An explicit approval label is required
before a validated test-only task can enter the bounded run-local queue.
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


def build_proposals(
    issues_path: Path, queue_path: Path, state_path: Path, output_path: Path, catalog_path: Path
) -> dict:
    issues = _object(issues_path)
    queue = _object(queue_path)
    state = _object(state_path)
    catalog = _object(catalog_path)
    if not isinstance(issues, list) or not isinstance(queue, dict) or not isinstance(state, dict):
        raise ValueError("invalid proposal input schema")
    catalog_tasks = catalog.get("tasks") if isinstance(catalog, dict) else None
    if not isinstance(catalog_tasks, list):
        raise ValueError("invalid registered task catalog")
    registered = {}
    for entry in catalog_tasks:
        if not isinstance(entry, dict):
            raise ValueError("invalid registered task definition")
        task_id = entry.get("id")
        instruction = entry.get("instruction")
        allowed_paths = entry.get("allowed_paths")
        if (
            not isinstance(task_id, str) or not task_id.strip()
            or not isinstance(instruction, str) or not instruction.strip()
            or not isinstance(allowed_paths, list) or not allowed_paths
            or not all(isinstance(path, str) and path.strip() for path in allowed_paths)
        ):
            raise ValueError("invalid registered task definition")
        normalized = {
            "id": task_id,
            "instruction": instruction.strip(),
            "allowed_paths": [path.strip() for path in allowed_paths],
        }
        if task_id in registered and registered[task_id] != normalized:
            raise ValueError("conflicting registered task definitions")
        registered[task_id] = normalized
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
        held = record.get("held", False)
        resume_requires_review = record.get("resume_requires_review", False)
        # Validate both flags before interpreting either one; a true flag must
        # not mask a malformed sibling flag in untrusted durable state.
        if type(held) is not bool or type(resume_requires_review) is not bool:
            raise ValueError("Recovery AI task flags are invalid")
        if held or resume_requires_review:
            excluded.add(task_id)

    proposals = []
    approved_tasks = []
    rejected_approved_tasks = []
    seen = set()
    max_tasks = queue.get("max_tasks_per_run", 4)
    if type(max_tasks) is not int or not 1 <= max_tasks <= 4:
        raise ValueError("invalid runtime task limit")
    queue_capacity = max(0, max_tasks - len(queued))
    for issue in issues[:100]:
        if not isinstance(issue, dict):
            raise ValueError("issue record is invalid")
        labels = issue.get("labels", [])
        if not isinstance(labels, list):
            raise ValueError("issue labels are invalid")
        label_names = {label.get("name") for label in labels if isinstance(label, dict)}
        if issue.get("state") != "open":
            continue
        # Approval is a separate, explicit human action. Candidate-only issues
        # remain review-only and can never enter the executable queue.
        approved = "autonomous-task-approved" in label_names
        candidate = "autonomous-task-candidate" in label_names
        if not approved and not candidate:
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
        fingerprint = hashlib.sha256(
            json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if approved:
            # Approval is necessary but not sufficient: the issue spec must
            # exactly match a separately reviewed, immutable-SHA catalog entry.
            if registered.get(spec["id"]) != spec:
                rejected_approved_tasks.append({
                    "id": spec["id"],
                    "source_issue": number,
                    "reason": "not_in_registered_catalog_or_spec_mismatch",
                })
                continue
            if len(approved_tasks) < min(4, queue_capacity):
                approved_tasks.append({**spec, "source_issue": number, "proposal_fingerprint": fingerprint})
                excluded.add(spec["id"])
            continue
        proposals.append({
            **spec,
            "source_issue": number,
            "status": "REVIEW_REQUIRED",
            "proposal_fingerprint": fingerprint,
        })
        if len(proposals) >= 4:
            break

    if approved_tasks:
        updated_queue = dict(queue)
        updated_queue["tasks"] = [*queued, *approved_tasks]
        queue_path.write_text(json.dumps(updated_queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if approved_tasks and proposals:
        status = "QUEUED_APPROVED_AND_REVIEW_REQUIRED"
    elif approved_tasks:
        status = "QUEUED_APPROVED"
    elif proposals:
        status = "REVIEW_REQUIRED"
    elif rejected_approved_tasks:
        status = "APPROVED_TASKS_REJECTED_UNREGISTERED"
    else:
        status = "NO_TRUSTED_CANDIDATES"
    result = {
        "version": 1,
        "status": status,
        "approved_count": len(approved_tasks),
        "approved_task_ids": [task["id"] for task in approved_tasks],
        "proposal_count": len(proposals),
        "proposals": proposals,
        "rejected_approved_count": len(rejected_approved_tasks),
        "rejected_approved_tasks": rejected_approved_tasks,
        "reason": (
            None if approved_tasks or proposals
            else "approved_issue_task_not_registered_or_spec_mismatch"
            if rejected_approved_tasks
            else "no_open_labeled_issue_with_valid_test_only_spec"
        ),
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
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_proposals(args.issues, args.queue, args.state, args.output, args.catalog)
    except (ValueError, OSError) as exc:
        print("TASK_PROPOSALS_BLOCKED: " + type(exc).__name__)
        return 2
    print(json.dumps({
        k: result[k] for k in (
            "status", "approved_count", "proposal_count",
            "rejected_approved_count", "reason"
        )
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
