"""Fail-closed, run-local policy admission for one verified test-only task.

The policy never edits the tracked catalog, durable state, or queue. It admits
at most one analyzer candidate per cycle into temporary runtime inputs, and
only after revalidating its source/test fingerprint and exact allowlisted path.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from scripts.autonomous_task_refill import _validate_task, read_json
from scripts.autonomous_task_target_allowlist import TARGETS
from scripts.catalog_exhaustion_analyzer import _public_functions, _referenced_symbols

POLICY_VERSION = "test-only-append-v1"
TASK_ID = re.compile(r"^review-coverage-gap-[a-f0-9]{10}$")
FUNCTION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")


def _safe_repo_file(root: Path, relative: str) -> Path:
    candidate = root / relative
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("candidate_path_contains_symlink")
    resolved_root = root.resolve()
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("candidate_path_escapes_repository") from exc
    if not resolved.is_file():
        raise ValueError("candidate_path_not_file")
    return resolved


def _validate_candidate(candidate: object, repo_root: Path) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ValueError("candidate_not_object")
    task_id = candidate.get("id")
    test_path = candidate.get("target_test")
    source_function = candidate.get("source_function")
    evidence = candidate.get("evidence")
    fingerprint = candidate.get("fingerprint")
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise ValueError("candidate_task_id_invalid")
    if not isinstance(test_path, str) or not isinstance(source_function, str) or not FUNCTION.fullmatch(source_function):
        raise ValueError("candidate_target_invalid")
    if not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("candidate_fingerprint_invalid")
    if candidate.get("status") != "REVIEW_REQUIRED":
        raise ValueError("candidate_status_invalid")
    matches = [pair for pair in TARGETS if pair[1] == test_path]
    if len(matches) != 1:
        raise ValueError("candidate_target_not_allowlisted")
    source_path, expected_test_path = matches[0]
    if not isinstance(evidence, str) or not re.fullmatch(re.escape(source_path) + r":[1-9][0-9]*", evidence):
        raise ValueError("candidate_evidence_invalid")
    expected_id = "review-coverage-gap-" + hashlib.sha256(
        f"{source_path}:{source_function}".encode("utf-8")
    ).hexdigest()[:10]
    if task_id != expected_id:
        raise ValueError("candidate_id_evidence_mismatch")

    source_file = _safe_repo_file(repo_root, source_path)
    test_file = _safe_repo_file(repo_root, expected_test_path)
    source_text = source_file.read_text(encoding="utf-8")
    test_text = test_file.read_text(encoding="utf-8")
    line = int(evidence.rsplit(":", 1)[1])
    if (source_function, line) not in _public_functions(source_text):
        raise ValueError("candidate_source_evidence_stale")
    try:
        ast.parse(test_text)
    except SyntaxError as exc:
        raise ValueError("candidate_test_file_syntax_invalid") from exc
    if source_function.rsplit(".", 1)[-1] in _referenced_symbols(test_text):
        raise ValueError("candidate_already_referenced_by_test_ast")
    expected_fingerprint = hashlib.sha256(
        f"{source_path}\0{source_function}\0{line}\0"
        f"{hashlib.sha256(source_text.encode()).hexdigest()}\0"
        f"{hashlib.sha256(test_text.encode()).hexdigest()}".encode()
    ).hexdigest()
    if fingerprint != expected_fingerprint:
        raise ValueError("candidate_fingerprint_stale")
    instruction = (
        f"自律ポリシー {POLICY_VERSION} による限定テストタスクです。"
        f"{test_path} の末尾に、{source_function} ({evidence}) の境界条件を検証する"
        "新しいpytest test関数を1つだけ追記してください。"
        "作業前に既存テスト・fixture・間接カバレッジを確認し、重複または不確実なら"
        "ファイルを変更せずNO_CHANGEとして理由を報告してください。"
        "既存の関数・assert・fixture・parametrize・classは変更、削除、改名、移動禁止。"
        "変更可能なのは指定テストファイル1つだけで、実装コード・workflow・catalog・stateは禁止。"
        "ネットワーク、シークレット、外部プロセス、マージ、デプロイは禁止。"
        "テストは決定的かつローカルで完結させ、ファイル操作が必要ならpytestのtmp_path内に限定してください。"
    )
    return {"id": task_id, "instruction": instruction, "allowed_paths": [test_path]}


def build_policy_admission(
    report: object,
    queue: object,
    catalog: object,
    state: object,
    repo_root: Path,
) -> dict[str, Any]:
    if not isinstance(queue, dict) or not isinstance(queue.get("tasks"), list):
        raise ValueError("runtime_queue_invalid")
    if not isinstance(catalog, dict) or not isinstance(catalog.get("tasks"), list):
        raise ValueError("task_catalog_invalid")
    if not isinstance(state, dict) or not isinstance(state.get("completed"), list):
        raise ValueError("durable_state_invalid")
    if not all(isinstance(item, str) for item in state["completed"]):
        raise ValueError("durable_completed_ids_invalid")
    recovery = state.get("recovery_ai")
    if (
        not isinstance(recovery, dict)
        or type(recovery.get("schema_version")) is not int
        or recovery.get("schema_version") != 1
        or not isinstance(recovery.get("tasks"), dict)
        or "checkpoint" not in recovery
    ):
        raise ValueError("recovery_state_invalid")

    existing_queue = [_validate_task(item) for item in queue["tasks"]]
    queued_ids = [item["id"] for item in existing_queue]
    if len(queued_ids) != len(set(queued_ids)):
        raise ValueError("runtime_queue_duplicate_ids")
    raw_catalog_tasks = catalog["tasks"]
    catalog_tasks = [_validate_task(item) for item in raw_catalog_tasks]
    catalog_ids = [item["id"] for item in catalog_tasks]
    if len(catalog_ids) != len(set(catalog_ids)):
        raise ValueError("catalog_duplicate_ids")

    cap = catalog.get("max_additions_per_run")
    max_tasks = queue.get("max_tasks_per_run", 4)
    if type(cap) is not int or not 1 <= cap <= 4:
        raise ValueError("catalog_addition_cap_invalid")
    if type(max_tasks) is not int or not 1 <= max_tasks <= 4:
        raise ValueError("runtime_task_cap_invalid")

    base_queue = dict(queue)
    base_catalog = dict(catalog)
    base_report = dict(report) if isinstance(report, dict) else {}
    result: dict[str, Any] = {
        "version": 1,
        "policy_version": POLICY_VERSION,
        "status": "POLICY_SKIPPED",
        "reason": "no_valid_candidate",
        "admitted_task_id": None,
        "max_tasks_per_cycle": 1,
        "persistent_catalog_modified": False,
        "durable_state_modified": False,
        "held_tasks_resumed": False,
        "execution_scope": "one_test_file_append_only",
    }

    # Existing approved work always takes precedence. This policy only fills an
    # otherwise empty run-local queue; it never adds work beside existing tasks.
    if existing_queue:
        result["reason"] = "existing_approved_queue_has_priority"
        return {"queue": base_queue, "catalog": base_catalog, "review_report": base_report, "report": result}
    if not isinstance(report, dict) or report.get("status") != "REVIEW_REQUIRED":
        result["reason"] = "analyzer_did_not_report_reviewable_candidates"
        return {"queue": base_queue, "catalog": base_catalog, "review_report": base_report, "report": result}
    safety = report.get("safety")
    candidates = report.get("candidates")
    if (
        not isinstance(safety, dict)
        or safety.get("read_only") is not True
        or safety.get("requires_human_review") is not True
        or safety.get("candidates_executable") is not False
        or not isinstance(candidates, list)
        or not candidates
        or report.get("candidate_count") != len(candidates)
    ):
        result["reason"] = "analyzer_safety_contract_invalid"
        return {"queue": base_queue, "catalog": base_catalog, "review_report": base_report, "report": result}

    completed = set(state["completed"])
    recovery_tasks = recovery["tasks"]
    for recovery_id, recovery_record in recovery_tasks.items():
        if not isinstance(recovery_id, str) or not isinstance(recovery_record, dict):
            raise ValueError("recovery_task_record_invalid")
        if type(recovery_record.get("held", False)) is not bool or type(recovery_record.get("resume_requires_review", False)) is not bool:
            raise ValueError("recovery_task_flags_invalid")
    registered = set(catalog_ids)
    excluded = registered | set(queued_ids) | completed | set(recovery_tasks)
    validated = None
    selected_index = None
    for index, candidate in enumerate(candidates):
        # Invalid/stale candidates are skipped, never partially admitted.
        try:
            spec = _validate_candidate(candidate, repo_root)
        except (OSError, UnicodeError, ValueError):
            continue
        if spec["id"] in excluded:
            continue
        validated, selected_index = spec, index
        break
    if validated is None or selected_index is None:
        result["reason"] = "no_candidate_passed_current_source_and_state_validation"
        return {"queue": base_queue, "catalog": base_catalog, "review_report": base_report, "report": result}

    # Runtime-only approval: the tracked catalog and durable task state are untouched.
    ephemeral_entry = {**validated, "execution_approved": True}
    base_catalog["tasks"] = [*raw_catalog_tasks, ephemeral_entry]
    base_queue["tasks"] = [{k: validated[k] for k in ("id", "instruction", "allowed_paths")}]
    base_queue["max_tasks_per_run"] = 1

    remaining = [item for i, item in enumerate(candidates) if i != selected_index]
    review_report = dict(report)
    review_report["candidates"] = remaining
    review_report["candidate_count"] = len(remaining)
    if remaining:
        review_report["status"] = "REVIEW_REQUIRED"
    else:
        review_report["status"] = "NO_SAFE_CANDIDATE"
        review_report["candidate_count"] = 0

    result.update({
        "status": "POLICY_ADMITTED",
        "reason": "one_current_fingerprint_verified_test_only_candidate_admitted_run_locally",
        "admitted_task_id": validated["id"],
        "admitted_allowed_path": validated["allowed_paths"][0],
        "remaining_review_candidate_count": len(remaining),
        "persistent_catalog_modified": False,
        "durable_state_modified": False,
        "held_tasks_resumed": False,
    })
    return {"queue": base_queue, "catalog": base_catalog, "review_report": review_report, "report": result}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output-queue", type=Path, required=True)
    parser.add_argument("--output-catalog", type=Path, required=True)
    parser.add_argument("--output-review-report", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args()
    try:
        analyzer = read_json(args.report)
        queue = read_json(args.queue)
        catalog = read_json(args.catalog)
        state = read_json(args.state)
        result = build_policy_admission(analyzer, queue, catalog, state, args.repo_root)
        _write_json(args.output_queue, result["queue"])
        _write_json(args.output_catalog, result["catalog"])
        _write_json(args.output_review_report, result["review_report"])
        _write_json(args.output_report, result["report"])
    except (OSError, UnicodeError, ValueError) as exc:
        print("AUTONOMOUS_TEST_ADMISSION_BLOCKED: " + type(exc).__name__)
        return 2
    print(json.dumps(result["report"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
