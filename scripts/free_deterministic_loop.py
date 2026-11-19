#!/usr/bin/env python3
"""Provider-free, fail-closed pilot for one deterministic regression-test task.

This runner intentionally does not import the existing Groq-dependent worker or
runtime. It applies only a source-controlled, fixed test insertion and never
pushes, creates a PR, merges, or deploys.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = {
    "distributed-loop-queue-progress-empty-queue-regression": {
        "target": "tests/test_distributed_loop_queue_progress.py",
        "test_name": "test_empty_runtime_queue_reports_zero_progress_for_not_run",
        "anchor": "def test_progress_uses_runtime_queue_and_counts_refill_tasks(tmp_path: Path):\n",
        "addition": (
            "def test_empty_runtime_queue_reports_zero_progress_for_not_run(tmp_path: Path):\n"
            "    queue = tmp_path / \"runtime-queue.json\"\n"
            "    state = tmp_path / \"state.json\"\n"
            "    results = tmp_path / \"results.jsonl\"\n"
            "    queue.write_text(json.dumps({\"tasks\": []}), encoding=\"utf-8\")\n"
            "    state.write_text(json.dumps({\"completed\": [\"prior-task\"]}), encoding=\"utf-8\")\n"
            "    results.write_text(json.dumps({\"task_id\": \"\", \"status\": \"NOT_RUN\", \"failure_reason\": \"queue_empty\"}), encoding=\"utf-8\")\n"
            "    assert calculate_progress(queue, state, results) == {\"queue_total\": 0, \"queue_completed\": 0}\n\n\n"
        ),
        "pytest_target": "tests/test_distributed_loop_queue_progress.py",
    }
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("git_" + args[0] + "_failed")
    return result.stdout.strip()


def emit(record: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def ast_test_signatures(source: str, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    return [
        ast.dump(node, include_attributes=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    ]


def build_candidate(task: dict, original: str) -> tuple[str, str]:
    spec = TASKS[task["id"]]
    if spec["test_name"] + "(" in original:
        return original, "NO_CHANGE"
    anchor = spec["anchor"]
    if original.count(anchor) != 1:
        raise RuntimeError("anchor_not_unique")
    replacement = spec["addition"] + anchor
    if len(anchor) > 1200 or len(replacement) > 1800:
        raise RuntimeError("patch_size_exceeded")
    candidate = original.replace(anchor, replacement, 1)
    before = ast_test_signatures(original, spec["target"])
    after = ast_test_signatures(candidate, spec["target"])
    if len(after) != len(before) + 1:
        raise RuntimeError("test_count_not_incremented")
    remaining = list(after)
    for signature in before:
        if signature not in remaining:
            raise RuntimeError("existing_test_modified")
        remaining.remove(signature)
    if len(remaining) != 1:
        raise RuntimeError("unexpected_test_delta")
    return candidate, "PATCHED"


def run_targeted_pytest(target: Path, original: str, patched: bool, pytest_target: str):
    """Run the focused test and restore the source on failure or interruption."""
    try:
        test = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=short", pytest_target],
            cwd=ROOT, text=True, capture_output=True, timeout=600, check=False,
        )
    except BaseException:
        if patched:
            target.write_text(original, encoding="utf-8")
        raise
    if test.returncode != 0 and patched:
        target.write_text(original, encoding="utf-8")
    return test


def run_task(task: dict) -> dict:
    task_id = task.get("id")
    if task_id not in TASKS:
        raise RuntimeError("task_not_allowlisted")
    spec = TASKS[task_id]
    if task.get("execution_approved") is not True:
        raise RuntimeError("execution_not_approved")
    if task.get("allowed_paths") != [spec["target"]]:
        raise RuntimeError("allowed_paths_mismatch")
    base_sha = task.get("base_sha")
    if not isinstance(base_sha, str) or not SHA_RE.fullmatch(base_sha):
        raise RuntimeError("invalid_base_sha")
    if git("rev-parse", "HEAD") != base_sha:
        raise RuntimeError("base_sha_mismatch")
    if git("status", "--porcelain"):
        raise RuntimeError("working_tree_not_clean")

    target = ROOT / spec["target"]
    if target.is_symlink() or not target.is_file():
        raise RuntimeError("target_not_regular_file")
    try:
        target.resolve().relative_to(ROOT.resolve())
    except ValueError:
        raise RuntimeError("target_outside_repository") from None
    original = target.read_text(encoding="utf-8")
    candidate, plan_status = build_candidate(task, original)
    digest_before = hashlib.sha256(original.encode("utf-8")).hexdigest()
    digest_after = hashlib.sha256(candidate.encode("utf-8")).hexdigest()

    if plan_status == "PATCHED":
        temporary = target.with_suffix(target.suffix + ".free-loop.tmp")
        try:
            temporary.write_text(candidate, encoding="utf-8")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    test = run_targeted_pytest(target, original, plan_status == "PATCHED", spec["pytest_target"])
    passed = test.returncode == 0

    return {
        "task_id": task_id,
        "status": "PASS" if passed else "FAIL",
        "plan_status": plan_status,
        "failure_reason": None if passed else "targeted_pytest_failed",
        "base_sha": base_sha,
        "target": spec["target"],
        "sha256_before": digest_before,
        "sha256_after": digest_after if passed else digest_before,
        "pytest_returncode": test.returncode,
        "pytest_output_tail": (test.stdout + "\n" + test.stderr)[-3000:],
        "persisted": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--approved-task-id", default=None)
    args = parser.parse_args()
    record_path = args.evidence
    try:
        queue = json.loads(args.queue.read_text(encoding="utf-8"))
        if not isinstance(queue, dict) or not isinstance(queue.get("tasks"), list):
            raise RuntimeError("invalid_queue_schema")
        if not queue["tasks"]:
            record = {
                "task_id": None, "status": "NO_TASK", "failure_reason": "approved_queue_empty",
                "timestamp": datetime.now(timezone.utc).isoformat(), "persisted": False,
            }
            emit(record, record_path)
            print("FREE_LOOP_STATUS=NO_TASK")
            return 0
        if len(queue["tasks"]) != 1:
            raise RuntimeError("pilot_accepts_exactly_one_task")
        if args.approved_task_id != queue["tasks"][0].get("id"):
            raise RuntimeError("explicit_workflow_approval_required")
        record = run_task(queue["tasks"][0])
        emit(record, record_path)
        print("FREE_LOOP_STATUS=" + record["status"])
        return 0 if record["status"] == "PASS" else 1
    except Exception as exc:
        record = {
            "task_id": None, "status": "BLOCKED",
            "failure_reason": str(exc)[:160],
            "timestamp": datetime.now(timezone.utc).isoformat(), "persisted": False,
        }
        emit(record, record_path)
        print("FREE_LOOP_STATUS=BLOCKED")
        print("FREE_LOOP_REASON=" + record["failure_reason"])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
