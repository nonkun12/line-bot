"""Generate reviewed task proposals and bounded, test-only autonomous fallback work.

Issue-derived tasks require an explicit approval label. When the curated queue is
empty, one deterministic test-only task may be queued from a fixed path allowlist.
The target-content fingerprint prevents repeating an unchanged NO_CHANGE task;
all generated work remains bounded and cannot edit production source.
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
AUTO_TEST_TARGETS = (
    "tests/test_autonomous_task_proposals.py",
    "tests/test_autonomous_task_refill.py",
    "tests/test_distributed_loop_queue_progress.py",
    "tests/test_control_tower_orchestrator.py",
    "tests/test_english_learning.py",
    "tests/test_recovery_ai.py",
)


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


def _auto_test_task(repo_root: Path, excluded: set[str]) -> dict | None:
    """Select one reviewed test target and fingerprint its current contents."""
    root = repo_root.resolve()
    for relative in AUTO_TEST_TARGETS:
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or not TEST_PATH.fullmatch(relative):
            continue
        try:
            content = candidate.read_bytes()
        except OSError:
            continue
        fingerprint = hashlib.sha256(content).hexdigest()
        stem = re.sub(r"[^a-z0-9-]+", "-", Path(relative).stem.lower()).strip("-")
        task_id = f"auto-test-{stem}-{fingerprint[:12]}"
        if task_id in excluded:
            continue
        instruction = (
            f"Review the existing tests in {relative} and read related implementation files "
            "for context, but edit only the single allowed test file. Add exactly one focused, "
            "non-duplicate regression test for a concrete uncovered edge case. Use dummy or "
            "temporary data only. If no clear uncovered behavior can be tested without guessing, "
            "make no change and report NO_CHANGE. Do not change implementation, configuration, "
            "workflow, dependency, or secret files. No network/external service access, no secrets, "
            "no OS/UI actions, no merge, and no deploy. Run the narrow test and report its evidence."
        )
        return {
            "id": task_id,
            "instruction": instruction,
            "allowed_paths": [relative],
            "source": "bounded_auto_test_refill",
            "target_fingerprint": fingerprint,
        }
    return None


def build_proposals(
    issues_path: Path,
    queue_path: Path,
    state_path: Path,
    output_path: Path,
    *,
    enable_auto_refill: bool = False,
    repo_root: Path | None = None,
) -> dict:
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
    if not isinstance(recovery, dict) or type(recovery.get("schema_version")) is not int or recovery.get("schema_version") != 1 or not isinstance(recovery.get("tasks"), dict) or "checkpoint" not in recovery:
        raise ValueError("Recovery AI state is invalid")

    excluded = {x.get("id") for x in queued if isinstance(x, dict) and isinstance(x.get("id"), str)} | set(completed)
    recovery_tasks = recovery["tasks"]
    for task_id, record in recovery_tasks.items():
        if not isinstance(task_id, str) or not isinstance(record, dict):
            raise ValueError("Recovery AI task record is invalid")
        held = record.get("held", False)
        resume_requires_review = record.get("resume_requires_review", False)
        if type(held) is not bool or type(resume_requires_review) is not bool:
            raise ValueError("Recovery AI task flags are invalid")
        if held or resume_requires_review:
            excluded.add(task_id)

    proposals = []
    approved_tasks = []
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
        approved = "autonomous-task-approved" in label_names
        candidate = "autonomous-task-candidate" in label_names
        if not approved and not candidate:
            continue
        spec = _spec(issue.get("body", ""))
        if spec is None or spec["id"] in excluded or spec["id"] in seen:
            continue
        number = issue.get("number")
        if type(number) is not int or number < 1:
            continue
        seen.add(spec["id"])
        fingerprint = hashlib.sha256(
            json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if approved:
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

    # Never inject fallback work ahead of an existing curated/approved queue.
    # At most one test-only task is added, and only from the fixed target list.
    auto_task = None
    if enable_auto_refill and not queued and not approved_tasks and queue_capacity > 0:
        auto_task = _auto_test_task(repo_root or Path.cwd(), excluded | seen)
        if auto_task is not None:
            approved_tasks.append(auto_task)

    if approved_tasks:
        updated_queue = dict(queue)
        updated_queue["tasks"] = [*queued, *approved_tasks]
        queue_path.write_text(json.dumps(updated_queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if auto_task is not None and proposals:
        status = "AUTO_QUEUED_AND_REVIEW_REQUIRED"
    elif auto_task is not None:
        status = "AUTO_QUEUED"
    elif approved_tasks and proposals:
        status = "QUEUED_APPROVED_AND_REVIEW_REQUIRED"
    elif approved_tasks:
        status = "QUEUED_APPROVED"
    elif proposals:
        status = "REVIEW_REQUIRED"
    else:
        status = "NO_TRUSTED_CANDIDATES"
    result = {
        "version": 1,
        "status": status,
        "approved_count": len(approved_tasks) if auto_task is None else 0,
        "approved_task_ids": [task["id"] for task in approved_tasks] if auto_task is None else [],
        "auto_queued_count": 1 if auto_task is not None else 0,
        "auto_queued_task_ids": [auto_task["id"]] if auto_task is not None else [],
        "proposal_count": len(proposals),
        "proposals": proposals,
        "reason": None if approved_tasks or proposals else "no_open_labeled_issue_with_valid_test_only_spec",
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
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--enable-auto-refill", action="store_true")
    args = parser.parse_args()
    try:
        result = build_proposals(
            args.issues, args.queue, args.state, args.output,
            enable_auto_refill=args.enable_auto_refill,
            repo_root=args.repo_root,
        )
    except (ValueError, OSError) as exc:
        print("TASK_PROPOSALS_BLOCKED: " + type(exc).__name__)
        return 2
    print(json.dumps({
        "status": result["status"],
        "proposal_count": result["proposal_count"],
        "auto_queued_count": result["auto_queued_count"],
        "reason": result["reason"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
