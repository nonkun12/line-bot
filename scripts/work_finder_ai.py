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
    held_count = sum(1 for item in records.values() if isinstance(item, dict) and item.get("held") is True)
    review_count = sum(
        1 for item in records.values()
        if isinstance(item, dict) and item.get("resume_requires_review") is True
    )
    candidate_count = report["candidate_count"]
    if candidate_count:
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
