"""Read-only, deterministic review proposals for exhausted autonomous task catalogs.

This tool never writes the runtime queue, durable state, catalog, or GitHub Issues.
Its heuristic candidates require human review and cannot be executed as-is.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

MAX_CANDIDATES = 4
TEST_PATH = re.compile(r"^(tests|uhip/tests)/test_[A-Za-z0-9_]+\.py$")
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
# Explicit code-to-test map: no paths are derived from untrusted input.
TARGETS = (
    ("core/line_development_runtime.py", "tests/test_line_development_runtime.py"),
    ("core/agent_runtime.py", "tests/test_agent_runtime.py"),
    ("core/management_router.py", "tests/test_management_router.py"),
    ("core/control_tower_orchestrator.py", "tests/test_control_tower_orchestrator.py"),
    ("core/recovery_ai.py", "tests/test_recovery_ai.py"),
)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("invalid analyzer JSON input") from exc


def _task_ids(value, field: str) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"invalid {field}")
    return set(value)


def _planned_ids(runtime_source: str) -> set[str]:
    try:
        tree = ast.parse(runtime_source)
    except SyntaxError as exc:
        raise ValueError("runtime source AST is invalid") from exc
    planned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_DETERMINISTIC_AUTONOMOUS_TASK_TARGETS"
            for target in node.targets
        ) and isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    planned.add(key.value)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_deterministic_autonomous_test_plan":
            for child in ast.walk(node):
                if not isinstance(child, ast.Compare):
                    continue
                operands = [child.left, *child.comparators]
                if not any(isinstance(value, ast.Name) and value.id == "task_id" for value in operands):
                    continue
                for value in operands:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        planned.add(value.value)
    return planned


def _public_functions(source: str) -> list[tuple[str, int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            found.append((node.name, node.lineno))
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and not member.name.startswith("_"):
                    found.append((f"{node.name}.{member.name}", member.lineno))
    return found


def analyze(repo_root: Path, catalog_path: Path, queue_path: Path, state_path: Path, runtime_path: Path) -> dict:
    catalog = _read_json(catalog_path)
    queue = _read_json(queue_path)
    state = _read_json(state_path)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("tasks"), list):
        raise ValueError("invalid catalog schema")
    if not isinstance(queue, dict) or not isinstance(queue.get("tasks"), list):
        raise ValueError("invalid queue schema")
    if not isinstance(state, dict) or not isinstance(state.get("recovery_ai"), dict):
        raise ValueError("invalid durable state schema")
    recovery = state["recovery_ai"]
    if type(recovery.get("schema_version")) is not int or recovery.get("schema_version") != 1 or not isinstance(recovery.get("tasks"), dict):
        raise ValueError("invalid Recovery AI state")
    catalog_ids = set()
    for item in catalog["tasks"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not TASK_ID.fullmatch(item["id"]):
            raise ValueError("invalid catalog task")
        if item["id"] in catalog_ids:
            raise ValueError("duplicate catalog task ID")
        catalog_ids.add(item["id"])
    queued_ids = set()
    for item in queue["tasks"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("invalid queued task")
        queued_ids.add(item["id"])
    completed = _task_ids(state.get("completed", []), "completed state")
    held, review = set(), set()
    for task_id, record in recovery["tasks"].items():
        if not isinstance(task_id, str) or not isinstance(record, dict):
            raise ValueError("invalid Recovery AI task entry")
        if type(record.get("held", False)) is not bool or type(record.get("resume_requires_review", False)) is not bool:
            raise ValueError("invalid Recovery AI flags")
        if record.get("held", False):
            held.add(task_id)
        if record.get("resume_requires_review", False):
            review.add(task_id)

    runtime_source = runtime_path.read_text(encoding="utf-8")
    planned = _planned_ids(runtime_source)
    missing_plan = sorted(catalog_ids - planned)
    excluded = queued_ids | completed | held | review | catalog_ids
    candidates = []
    for code_rel, test_rel in TARGETS:
        if len(candidates) >= MAX_CANDIDATES:
            break
        code_path, test_path = repo_root / code_rel, repo_root / test_rel
        if not code_path.is_file() or not test_path.is_file():
            continue
        if test_path.is_symlink() or not TEST_PATH.fullmatch(test_rel):
            continue
        code_source = code_path.read_text(encoding="utf-8")
        test_source = test_path.read_text(encoding="utf-8")
        for function, line in _public_functions(code_source):
            if len(candidates) >= MAX_CANDIDATES:
                break
            leaf = function.rsplit(".", 1)[-1]
            # Conservative textual heuristic only. It is explicitly marked as
            # review-only because indirect/parameterized coverage is possible.
            if re.search(r"\b" + re.escape(leaf) + r"\b", test_source):
                continue
            # Stable across line movement; source location remains in evidence/fingerprint.
            suffix = hashlib.sha256(f"{code_rel}:{function}".encode()).hexdigest()[:10]
            task_id = f"review-coverage-gap-{suffix}"
            if task_id in excluded:
                continue
            evidence = f"{code_rel}:{line}"
            fingerprint = hashlib.sha256(
                f"{code_rel}\0{function}\0{line}\0{hashlib.sha256(code_source.encode()).hexdigest()}\0{hashlib.sha256(test_source.encode()).hexdigest()}".encode()
            ).hexdigest()
            candidates.append({
                "id": task_id,
                "instruction": f"人手レビュー後に限り、{test_rel} に {code_rel} の {function} ({evidence}) の境界条件を検証する新しい回帰テストを1件追加してください。既存テストを変更せず、指定テストファイルのみ変更してください。候補生成はテスト未参照の文字列ヒューリスティックに基づくため、間接カバレッジや既存テストとの重複を先に確認してください。外部通信・シークレット・OS操作・マージ・デプロイは禁止。",
                "target_test": test_rel,
                "evidence": evidence,
                "source_function": function,
                "status": "REVIEW_REQUIRED",
                "heuristic": "public-symbol-name-not-found-in-test-source; may have indirect coverage",
                "fingerprint": fingerprint,
            })
    return {
        "version": 1,
        "status": "REVIEW_REQUIRED" if candidates else "NO_SAFE_CANDIDATE",
        "reason": None if candidates else "no_allowlisted_unreferenced_public_symbols_found",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "catalog_ids_without_runtime_plan": missing_plan,
        "runtime_plan_count": len(planned),
        "safety": {
            "read_only": True,
            "queue_or_catalog_mutated": False,
            "durable_state_mutated": False,
            "requires_human_review": True,
            "candidates_executable": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = analyze(args.repo_root, args.catalog, args.queue, args.state, args.runtime)
    except (ValueError, OSError) as exc:
        print(f"CATALOG_EXHAUSTION_ANALYZER_BLOCKED: {type(exc).__name__}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "candidate_count": report["candidate_count"],
        "catalog_ids_without_runtime_plan_count": len(report["catalog_ids_without_runtime_plan"]),
        "reason": report["reason"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
