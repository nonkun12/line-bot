"""Continuous, read-only work discovery for the distributed development loop.

Work Finder AI coordinates deterministic discovery signals and emits the same
review-only candidate contract consumed by autonomous_task_issue_drafts.
It never admits work to the execution queue or changes durable state/catalog.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.autonomous_task_target_allowlist import TARGETS
from scripts.autonomous_task_refill import _validate_task
from scripts.catalog_exhaustion_analyzer import analyze


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid Work Finder input: {path.name}") from exc


def find_work(
    repo_root: Path,
    catalog_path: Path,
    queue_path: Path,
    state_path: Path,
    runtime_path: Path,
    existing_issues_path: Path | None = None,
) -> dict:
    """Run repeatable discovery and classify what should happen next."""
    report = analyze(
        repo_root,
        catalog_path,
        queue_path,
        state_path,
        runtime_path,
        existing_issues_path,
    )
    catalog = _read_json(catalog_path)
    queue = _read_json(queue_path)
    state = _read_json(state_path)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("tasks"), list):
        raise ValueError("invalid catalog schema")
    if not isinstance(queue, dict) or not isinstance(queue.get("tasks"), list):
        raise ValueError("invalid queue schema")
    recovery = state.get("recovery_ai") if isinstance(state, dict) else None
    if not isinstance(recovery, dict) or not isinstance(recovery.get("tasks"), dict):
        raise ValueError("invalid Recovery AI state")

    existing_targets = [
        {"source": source, "test": test}
        for source, test in TARGETS
        if (repo_root / source).is_file() and (repo_root / test).is_file()
        and not (repo_root / source).is_symlink()
        and not (repo_root / test).is_symlink()
    ]
    records = recovery["tasks"]
    held_ids = {
        task_id for task_id, item in records.items()
        if isinstance(task_id, str) and isinstance(item, dict) and item.get("held") is True
    }
    review_ids = {
        task_id for task_id, item in records.items()
        if isinstance(task_id, str) and isinstance(item, dict)
        and item.get("resume_requires_review") is True
    }
    held_count = len(held_ids)
    review_count = len(review_ids)
    candidate_count = report["candidate_count"]

    # Mirror the queue-refill admission boundary for observability. Catalog
    # membership alone is not enough: only exact execution_approved=True tasks
    # with an unchanged queue definition and no completion/HOLD/review gate can
    # be counted as executable. This is diagnostic only; it grants no approval
    # and never mutates the queue or durable state.
    completed = state.get("completed", [])
    if not isinstance(completed, list) or not all(isinstance(item, str) for item in completed):
        raise ValueError("invalid completed task state")
    completed_ids = set(completed)
    queued_by_id = {}
    for item in queue["tasks"]:
        normalized = _validate_task(item)
        if normalized["id"] in queued_by_id:
            raise ValueError("duplicate runtime queue task ID")
        queued_by_id[normalized["id"]] = normalized
    catalog_by_id = {}
    for item in catalog["tasks"]:
        normalized = _validate_task(item)
        if normalized["id"] in catalog_by_id:
            raise ValueError("duplicate catalog task ID")
        catalog_by_id[normalized["id"]] = normalized

    approved_ids = {
        task_id for task_id, item in catalog_by_id.items()
        if item.get("execution_approved") is True
    }
    queue_executable_ids = []
    for task_id, queued in queued_by_id.items():
        trusted = catalog_by_id.get(task_id)
        if (
            trusted is not None
            and trusted.get("execution_approved") is True
            and all(queued.get(key) == trusted.get(key) for key in ("id", "instruction", "allowed_paths"))
            and task_id not in completed_ids
            and task_id not in held_ids
            and task_id not in review_ids
        ):
            queue_executable_ids.append(task_id)
    refill_eligible_ids = sorted(
        approved_ids
        - set(queued_by_id)
        - completed_ids
        - held_ids
        - review_ids
    )
    execution_eligible_ids = sorted(queue_executable_ids) + refill_eligible_ids

    if execution_eligible_ids:
        next_action = "run_approved_queue_tasks"
        cycle_status = "EXECUTION_ELIGIBLE_WORK_FOUND"
    elif candidate_count:
        next_action = "human_review_candidates"
        cycle_status = "WORK_FOUND"
    elif report["catalog_ids_without_runtime_plan"]:
        next_action = "review_catalog_runtime_plan_gaps"
        cycle_status = "NO_SAFE_CANDIDATE"
    else:
        next_action = "expand_allowlisted_discovery_sources"
        cycle_status = "NO_SAFE_CANDIDATE"

    # Preserve the exact analyzer schema expected by the existing safe issue
    # draft builder. Additional metadata is diagnostic only, never executable.
    report["work_finder"] = {
        "name": "Work Finder AI",
        "version": 1,
        "cycle_status": cycle_status,
        "next_action": next_action,
        "discovery_mode": "read_only_deterministic",
        "scanned_target_pairs": len(existing_targets),
        "catalog_task_count": len(catalog["tasks"]),
        "runtime_queue_task_count": len(queue["tasks"]),
        "held_task_count": held_count,
        "resume_review_required_count": review_count,
        "candidate_count": candidate_count,
        "discovered_candidate_count": candidate_count,
        "review_pending_count": candidate_count,
        "completed_task_count": len(state.get("completed", [])) if isinstance(state.get("completed", []), list) else 0,
        # This count mirrors the existing refill admission rules; it is not
        # an authorization decision and does not alter execution_approved.
        "approved_catalog_task_count": len(approved_ids),
        "queued_execution_eligible_count": len(queue_executable_ids),
        "queue_refill_eligible_count": len(refill_eligible_ids),
        "execution_eligible_count": len(execution_eligible_ids),
        "execution_eligible_task_ids": execution_eligible_ids,
        "execution_eligibility_status": (
            "eligible_tasks_present" if execution_eligible_ids else "none"
        ),
        "candidate_policy": "review_only_no_execution_approval",
        "repeat_policy": "run_on_every_normal_distributed_loop_cycle",
        "exhaustion_policy": (
            "continue_discovery_on_next_cycle; do_not_invent_or_auto_approve_tasks"
        ),
        "safety": {
            "read_only": True,
            "runtime_queue_mutated": False,
            "catalog_mutated": False,
            "durable_state_mutated": False,
            "issues_created": False,
            "execution_approval_granted": False,
        "execution_eligibility_is_authorization": False,
        },
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--existing-issues", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = find_work(
            args.repo_root, args.catalog, args.queue, args.state,
            args.runtime, args.existing_issues,
        )
    except (ValueError, OSError) as exc:
        print(f"WORK_FINDER_BLOCKED: {type(exc).__name__}: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "cycle_status": report["work_finder"]["cycle_status"],
        "next_action": report["work_finder"]["next_action"],
        "candidate_count": report["candidate_count"],
        "scanned_target_pairs": report["work_finder"]["scanned_target_pairs"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
