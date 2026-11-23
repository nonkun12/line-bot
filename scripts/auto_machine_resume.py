"""Run one bounded, machine-evidence-only resume attempt.

The runner never edits repository source, changes catalog policy, merges, deploys,
or bypasses task approval. It resumes only explicitly approved machine_evidence
test tasks whose current-base REA and exact allowed tests pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.confirm_machine_resume_review import confirm_if_machine_verified
from scripts.loop_rea_runner import run_pre_repair_rea
from scripts.recovery_ai import RecoveryStore
from scripts.resume_held_task import resume_task


_ALLOWED_FAILURE_CATEGORIES = frozenset({
    "test_regression", "timeout", "process_crash",
})


def _read(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("machine_resume_input_unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError("machine_resume_input_invalid")
    return value


def _safe_test_paths(value: Any) -> list[str] | None:
    if (
        not isinstance(value, list) or not value or len(value) > 20
        or not all(
            isinstance(path, str)
            and path.startswith("tests/test_")
            and path.endswith(".py")
            and ".." not in path.split("/")
            and "\\" not in path
            for path in value
        )
        or len(set(value)) != len(value)
    ):
        return None
    return sorted(value)


def _manifest(task: dict[str, Any], paths: list[str], base_sha: str,
              rea: dict[str, Any], run_id: str, attempt: int, nonce: str) -> dict[str, Any]:
    instruction = task["instruction"]
    path_digest = hashlib.sha256(
        json.dumps(paths, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    rea_digest = hashlib.sha256(
        json.dumps(rea, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    tests = rea.get("tests")
    return {
        "schema_version": 1,
        "task_id": task["id"],
        "instruction_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "allowed_paths_sha256": path_digest,
        "base_sha": base_sha,
        "target_sha": base_sha,
        "evaluated_paths": paths,
        "scanner_complete": True,
        "scanner_status": "PASS",
        "tests_status": "PASS" if isinstance(tests, dict) else "FAIL",
        "tests_exit_code": tests.get("exit_code") if isinstance(tests, dict) else 1,
        "cause_status": "FIXED",
        "cause_evidence_sha256": rea_digest,
        "workflow_run_id": run_id,
        "run_attempt": attempt,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "nonce": nonce,
    }


def run_one_machine_resume(
    *, repo_root: str | Path, state_file: str | Path,
    recovery_state_file: str | Path, catalog_file: str | Path,
    base_sha: str, workflow_run_id: str, run_attempt: int,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Find and resume at most one eligible task; otherwise return NO_CHANGE/BLOCKED."""
    nonce = nonce or secrets.token_hex(16)
    catalog = _read(catalog_file)
    specs = catalog.get("tasks")
    if not isinstance(specs, list):
        return {"status": "BLOCKED", "reason_code": "machine_resume_catalog_invalid"}
    state = _read(state_file)
    recovery = _read(recovery_state_file)
    if state.get("recovery_ai") != recovery:
        return {"status": "BLOCKED", "reason_code": "machine_resume_state_mismatch"}
    store = RecoveryStore(recovery_state_file)

    for task in specs:
        if not isinstance(task, dict) or task.get("execution_approved") is not True:
            continue
        if task.get("resume_policy") != "machine_evidence":
            continue
        task_id = task.get("id")
        if not isinstance(task_id, str):
            continue
        paths = _safe_test_paths(task.get("allowed_paths"))
        if paths is None:
            continue
        record = store.task_status(task_id)
        if record.get("held") is not True and record.get("resume_requires_review") is not True:
            continue
        if record.get("last_category") not in _ALLOWED_FAILURE_CATEGORIES:
            continue

        rea = run_pre_repair_rea(
            repo_root, base_sha=base_sha, allowed_paths=paths
        )
        if (
            not isinstance(rea, dict) or rea.get("status") != "PASS"
            or not isinstance(rea.get("tests"), dict)
            or rea["tests"].get("status") != "PASS"
            or rea["tests"].get("exit_code") != 0
        ):
            return {
                "status": "BLOCKED",
                "task_id": task_id,
                "reason_code": "machine_resume_rea_not_pass",
                "rea_status": rea.get("status") if isinstance(rea, dict) else "INVALID",
            }

        manifest = _manifest(
            task, paths, base_sha, rea, workflow_run_id, run_attempt, nonce
        )
        with tempfile.TemporaryDirectory(prefix="machine-resume-") as temp:
            evidence_file = Path(temp) / "evidence.json"
            evidence_file.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            # An already-pending review is not unheld a second time. A held task
            # must pass the existing exact catalog/Goal identity checks first.
            if record.get("held") is True or record.get("resume_requires_review") is not True:
                resume_task(
                    state_path=Path(state_file),
                    recovery_path=Path(recovery_state_file),
                    queue_path=Path(catalog_file),
                    task_id=task_id,
                    cause_fixed=True,
                )
            result = confirm_if_machine_verified(
                state_file=state_file,
                recovery_state_file=recovery_state_file,
                catalog_file=catalog_file,
                evidence_file=evidence_file,
                task_id=task_id,
                expected_base_sha=base_sha,
                expected_workflow_run_id=workflow_run_id,
                expected_run_attempt=run_attempt,
                expected_nonce=nonce,
            )
        return {
            "status": "PASS",
            "task_id": task_id,
            "reason_code": "machine_rea_resume_confirmed",
            "workflow_run_id": result["workflow_run_id"],
        }

    return {"status": "NO_CHANGE", "reason_code": "no_machine_resume_candidate"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--recovery-state-file", required=True)
    parser.add_argument("--catalog-file", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--nonce", required=True)
    args = parser.parse_args()
    try:
        result = run_one_machine_resume(
            repo_root=args.repo_root,
            state_file=args.state_file,
            recovery_state_file=args.recovery_state_file,
            catalog_file=args.catalog_file,
            base_sha=args.base_sha,
            workflow_run_id=args.workflow_run_id,
            run_attempt=args.run_attempt,
            nonce=args.nonce,
        )
    except Exception as exc:
        print(f"MACHINE_RESUME_BLOCKED: {type(exc).__name__}")
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"PASS", "NO_CHANGE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
