"""Register a human-approved, analyzer-generated test-only candidate in the task catalog.

This creates a reviewable catalog change only. It never queues or executes the task,
clears Recovery AI state, or creates a merge/deployment action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from scripts.autonomous_task_target_allowlist import TARGETS
from scripts.catalog_exhaustion_analyzer import _public_functions

SPEC_MARKER = "<!-- autonomous-task-spec -->"
TASK_ID = re.compile(r"^review-coverage-gap-[a-f0-9]{10}$")
INSTRUCTION_LIMIT = 2000
MAX_CATALOG_TASKS = 200
TICK = chr(96)


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("registration input is missing or invalid") from exc


def _validated_spec(issue: object, repo_root: Path) -> tuple[dict[str, Any], int]:
    if not isinstance(issue, dict) or issue.get("state") != "open" or "pull_request" in issue:
        raise ValueError("candidate must be an open GitHub issue")
    number = issue.get("number")
    if type(number) is not int or number < 1:
        raise ValueError("candidate issue number is invalid")
    labels = issue.get("labels")
    if not isinstance(labels, list) or any(not isinstance(label, dict) or not isinstance(label.get("name"), str) for label in labels):
        raise ValueError("candidate issue labels are invalid")
    label_names = {label["name"] for label in labels}
    catalog_approved = (
        "autonomous-task-catalog-approved" in label_names
        or "autonomous-task-approved" in label_names  # legacy registration-only label
    )
    if "autonomous-task-candidate" not in label_names or not catalog_approved:
        raise ValueError("candidate and explicit catalog-approval labels are required")

    body = issue.get("body")
    if not isinstance(body, str) or body.count(SPEC_MARKER) != 2:
        raise ValueError("candidate issue task spec markers are invalid")
    _, raw_spec, _ = body.split(SPEC_MARKER)
    try:
        spec = json.loads(raw_spec.strip())
    except json.JSONDecodeError as exc:
        raise ValueError("candidate issue task spec is invalid") from exc
    if not isinstance(spec, dict) or set(spec) != {"id", "instruction", "allowed_paths"}:
        raise ValueError("candidate issue task spec schema is invalid")

    task_id = spec.get("id")
    instruction = spec.get("instruction")
    paths = spec.get("allowed_paths")
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise ValueError("candidate task ID is not an analyzer-generated ID")
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > INSTRUCTION_LIMIT:
        raise ValueError("candidate task instruction is invalid")
    if not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], str):
        raise ValueError("candidate task must have exactly one allowed test path")
    matching = [pair for pair in TARGETS if pair[1] == paths[0]]
    if len(matching) != 1:
        raise ValueError("candidate test path is not in the analyzer allowlist")

    source_path, test_path = matching[0]
    evidence_matches = re.findall(
        r"- Source evidence: " + re.escape(TICK) + re.escape(source_path) + r":([1-9][0-9]*)" + re.escape(TICK),
        body,
    )
    function_matches = re.findall(
        r"- Source function: " + re.escape(TICK) + r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)" + re.escape(TICK),
        body,
    )
    fingerprint_matches = re.findall(
        r"- Analyzer fingerprint: " + re.escape(TICK) + r"([a-f0-9]{64})" + re.escape(TICK),
        body,
    )
    if len(evidence_matches) != 1 or len(function_matches) != 1 or len(fingerprint_matches) != 1:
        raise ValueError("candidate source evidence or analyzer fingerprint is missing or ambiguous")

    line = int(evidence_matches[0])
    source_function = function_matches[0]
    fingerprint = fingerprint_matches[0]
    evidence = f"{source_path}:{line}"
    expected_suffix = hashlib.sha256(f"{source_path}:{source_function}".encode("utf-8")).hexdigest()[:10]
    if task_id != f"review-coverage-gap-{expected_suffix}":
        raise ValueError("candidate task ID does not match its source evidence")
    if "- Allowed change: 指定されたテストファイル1つのみ" not in body:
        raise ValueError("candidate issue is missing its exact-path safety marker")
    if "Queue admission: not authorized" not in body:
        raise ValueError("candidate issue is missing its review-only safety marker")

    root = repo_root.resolve()
    source_file = root / source_path
    test_file = root / test_path
    for candidate_file in (source_file, test_file):
        if candidate_file.is_symlink() or not candidate_file.is_file():
            raise ValueError("candidate source or test file is missing or unsafe")
        try:
            candidate_file.resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError("candidate source or test file escapes repository root") from exc

    source_text = source_file.read_text(encoding="utf-8")
    test_text = test_file.read_text(encoding="utf-8")
    if (source_function, line) not in _public_functions(source_text):
        raise ValueError("candidate source function or line no longer matches current source")
    if re.search(r"\b" + re.escape(source_function.rsplit(".", 1)[-1]) + r"\b", test_text):
        raise ValueError("candidate is stale: target test now references the source function")
    expected_fingerprint = hashlib.sha256(
        f"{source_path}\0{source_function}\0{line}\0{hashlib.sha256(source_text.encode()).hexdigest()}\0{hashlib.sha256(test_text.encode()).hexdigest()}".encode()
    ).hexdigest()
    if fingerprint != expected_fingerprint:
        raise ValueError("candidate analyzer fingerprint does not match current source and test files")

    expected_instruction = (
        f"人手レビュー後に限り、{paths[0]} に {source_function} ({evidence}) の"
        "境界条件を検証する新しい回帰テストを1件追加してください。"
        "まず既存テストと間接カバレッジを確認し、重複する場合は変更せず理由を報告してください。"
        "変更は指定テストファイル1つだけ。実装コード・workflow・catalog・stateは変更禁止。"
        "外部通信・シークレット参照・OS操作・マージ・デプロイは禁止。"
    )
    if instruction.strip() != expected_instruction:
        raise ValueError("candidate instruction differs from the validated test-only template")

    return {
        "id": task_id,
        "instruction": expected_instruction,
        "allowed_paths": paths,
    }, number


def register_approved_candidate(
    issue: object, catalog: object, state: object, repo_root: Path = Path(".")
) -> tuple[dict[str, Any], bool]:
    spec, issue_number = _validated_spec(issue, repo_root)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("tasks"), list):
        raise ValueError("task catalog schema is invalid")
    if not isinstance(state, dict) or not isinstance(state.get("completed"), list):
        raise ValueError("durable loop state is invalid")
    if not all(isinstance(task_id, str) for task_id in state["completed"]):
        raise ValueError("durable completed-task state is invalid")
    recovery = state.get("recovery_ai")
    if (
        not isinstance(recovery, dict)
        or type(recovery.get("schema_version")) is not int
        or recovery.get("schema_version") != 1
        or not isinstance(recovery.get("tasks"), dict)
    ):
        raise ValueError("durable Recovery AI state is invalid")

    task_id = spec["id"]
    if task_id in state["completed"]:
        raise ValueError("candidate task is already completed")
    record = recovery["tasks"].get(task_id)
    if record is not None:
        if not isinstance(record, dict):
            raise ValueError("candidate Recovery AI record is invalid")
        held = record.get("held", False)
        review = record.get("resume_requires_review", False)
        if type(held) is not bool or type(review) is not bool:
            raise ValueError("candidate Recovery AI flags are invalid")
        if held or review:
            raise ValueError("candidate task is held or requires Recovery AI review")

    tasks = catalog["tasks"]
    for existing in tasks:
        if not isinstance(existing, dict) or not isinstance(existing.get("id"), str):
            raise ValueError("task catalog contains an invalid entry")
        if existing["id"] == task_id:
            if existing == spec:
                return {
                    "status": "ALREADY_REGISTERED",
                    "task_id": task_id,
                    "source_issue": issue_number,
                }, False
            raise ValueError("candidate task ID conflicts with an existing catalog definition")
    if len(tasks) >= MAX_CATALOG_TASKS:
        raise ValueError("task catalog reached its bounded registration limit")

    return {
        "status": "REGISTERED_FOR_REVIEW",
        "task_id": task_id,
        "source_issue": issue_number,
        "catalog_entry": spec,
    }, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        issue = _load(args.issue)
        catalog = _load(args.catalog)
        state = _load(args.state)
        result, changed = register_approved_candidate(issue, catalog, state, args.repo_root)
        if changed:
            updated = dict(catalog)
            updated["tasks"] = [*catalog["tasks"], result["catalog_entry"]]
            args.catalog.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result.pop("catalog_entry", None)
    except (OSError, ValueError) as exc:
        print(f"AUTONOMOUS_TASK_CATALOG_REGISTRATION_BLOCKED: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
