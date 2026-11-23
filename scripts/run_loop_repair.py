"""Explicit, fail-closed entrypoint for one catalog-approved local repair.

No task is selected automatically. The caller supplies only a task ID and a
Recovery AI state file. Catalog approval, failure identity, hold state, and
current HEAD are re-read from trusted repository/state sources.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False, timeout=20,
    )
    if result.returncode:
        raise RuntimeError("repair_git_evidence_unavailable")
    return result.stdout.strip()


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "status": "BLOCKED", "reason_code": reason,
        "repair_executed": False, "hold_clear_authorized": False,
        "resume_authorized": False, "merge_deploy_authorized": False,
    }


def run(task_id: str, recovery_state_path: str | Path, token: str) -> dict[str, Any]:
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", task_id):
        return _blocked("task_id_invalid")
    if not token:
        return _blocked("github_repair_ledger_token_missing")
    try:
        base_sha = _git("rev-parse", "HEAD")
        if _git("status", "--porcelain", "--untracked-files=all"):
            return _blocked("repository_not_clean")
        raw_catalog = _git("show", f"{base_sha}:.github/autonomous-loop-task-catalog.json")
        catalog = json.loads(raw_catalog)
        tasks = catalog.get("tasks") if isinstance(catalog, dict) else None
        if not isinstance(tasks, list):
            return _blocked("catalog_invalid")
        matches = [item for item in tasks if isinstance(item, dict) and item.get("id") == task_id]
        if len(matches) != 1:
            return _blocked("catalog_task_missing_or_duplicated")
        task = matches[0]
        instruction = task.get("instruction")
        paths = task.get("allowed_paths")
        if (
            task.get("repair_approved") is not True
            or task.get("execution_approved") is not True
            or not isinstance(instruction, str) or not instruction.strip()
            or not isinstance(paths, list) or not paths
            or not all(isinstance(path, str) and path and path == path.strip() for path in paths)
            or len(set(paths)) != len(paths)
        ):
            return _blocked("catalog_repair_or_execution_approval_missing")

        from scripts.recovery_ai import RecoveryStore
        record = RecoveryStore(recovery_state_path).task_status(task_id)
        if (
            record.get("held") is not False
            or record.get("resume_requires_review") is True
            or record.get("last_category") not in {"test_regression", "timeout", "process_crash"}
            or not isinstance(record.get("last_fingerprint"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", record["last_fingerprint"])
            or record.get("same_fingerprint_attempts") != 1
        ):
            return _blocked("recovery_state_not_eligible_for_single_repair")

        from scripts.loop_rea_runner import run_pre_repair_rea
        pre_rea = run_pre_repair_rea(ROOT, base_sha=base_sha, allowed_paths=paths)
        if (
            pre_rea.get("status") != "PASS"
            or pre_rea.get("base_sha") != base_sha
            or pre_rea.get("independent") is not True
        ):
            return _blocked("pre_repair_rea_not_pass")

        evidence = {
            "task_id": task_id,
            "instruction": instruction,
            "instruction_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
            "base_sha": base_sha,
            "current_head_sha": _git("rev-parse", "HEAD"),
            "failure_fingerprint": record["last_fingerprint"],
            "allowed_paths": paths,
            "catalog_repair_approved": True,
            "execution_approved": True,
            "held": False,
            "working_tree_clean": True,
            "rea_status": "PRE_REPAIR_PASS",
            "failure_category": record["last_category"],
            "repair_attempts": 0,
        }
        from scripts.loop_repair_executor import execute_one_repair
        repair_executor = None
        catalog_patch = task.get("repair_patch")
        catalog_patch_sha = task.get("repair_patch_sha256")
        if catalog_patch is not None or catalog_patch_sha is not None:
            if (
                not isinstance(catalog_patch, str)
                or not isinstance(catalog_patch_sha, str)
                or hashlib.sha256(catalog_patch.encode("utf-8")).hexdigest() != catalog_patch_sha
            ):
                return _blocked("catalog_repair_patch_hash_missing_or_invalid")
            from scripts.loop_catalog_patch_adapter import create_catalog_patch_adapter
            repair_executor = create_catalog_patch_adapter(ROOT, catalog_patch, catalog_patch_sha)
        result = execute_one_repair(
            evidence,
            token=token,
            repair_executor=repair_executor,
            repo_root=ROOT,
        )
        return {
            **result,
            "pre_repair_rea": pre_rea,
            "merge_deploy_authorized": False,
        }
    except Exception as exc:
        return _blocked("repair_orchestration_error:" + type(exc).__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--recovery-state", required=True, type=Path)
    args = parser.parse_args(argv)
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    result = run(args.task_id, args.recovery_state, token)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "REPAIR_VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
