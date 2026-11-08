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

from scripts.autonomous_task_target_allowlist import TARGETS

MAX_CANDIDATES = 4
TEST_PATH = re.compile(r"^(tests|uhip/tests)/test_[A-Za-z0-9_]+\.py$")
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
REVIEW_TASK_ID = re.compile(r"^review-coverage-gap-[a-f0-9]{10}$")
SPEC_MARKER = "<!-- autonomous-task-spec -->"
# Explicit code-to-test map: no paths are derived from untrusted input.

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
                for left, right in zip(operands, operands[1:]):
                    if isinstance(left, ast.Name) and left.id == "task_id" and isinstance(right, ast.Constant) and isinstance(right.value, str):
                        planned.add(right.value)
                    elif isinstance(right, ast.Name) and right.id == "task_id" and isinstance(left, ast.Constant) and isinstance(left.value, str):
                        planned.add(left.value)
    return planned


def _is_non_executable_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Ignore Protocol/ABC-style declarations that have no executable body."""
    decorator_names = {
        item.id if isinstance(item, ast.Name) else item.attr if isinstance(item, ast.Attribute) else ""
        for item in node.decorator_list
    }
    if decorator_names.intersection({"abstractmethod", "overload"}):
        return True
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        return True
    return all(
        isinstance(item, ast.Pass)
        or (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and item.value.value is Ellipsis)
        or (
            isinstance(item, ast.Raise)
            and isinstance(item.exc, ast.Call)
            and isinstance(item.exc.func, ast.Name)
            and item.exc.func.id == "NotImplementedError"
        )
        for item in body
    )


def _public_functions(source: str) -> list[tuple[str, int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            if not _is_non_executable_stub(node):
                found.append((node.name, node.lineno))
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if (
                    isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not member.name.startswith("_")
                    and not _is_non_executable_stub(member)
                ):
                    found.append((f"{node.name}.{member.name}", member.lineno))
    return found


def _referenced_symbols(test_source: str) -> set[str]:
    """Collect executable Python name/attribute references, not comments or strings."""
    try:
        tree = ast.parse(test_source)
    except SyntaxError as exc:
        raise ValueError("test source AST is invalid") from exc

    imported_names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_names[alias.asname or alias.name] = alias.name.rsplit(".", 1)[-1]

    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            referenced.add(node.id)
            original = imported_names.get(node.id)
            if original:
                referenced.add(original)
        elif isinstance(node, ast.Attribute):
            referenced.add(node.attr)
    return referenced


def _existing_issue_task_ids(issues_path: Path | None) -> set[str]:
    """Exclude every previously issued review candidate before selecting the next batch."""
    if issues_path is None:
        return set()
    issues = _read_json(issues_path)
    if not isinstance(issues, list):
        raise ValueError("existing issues must be a list")
    found: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("existing issue entry is invalid")
        body = issue.get("body")
        if not isinstance(body, str) or body.count(SPEC_MARKER) != 2:
            continue
        try:
            _, raw_spec, _ = body.split(SPEC_MARKER)
            spec = json.loads(raw_spec.strip())
        except (ValueError, TypeError):
            continue
        task_id = spec.get("id") if isinstance(spec, dict) else None
        if isinstance(task_id, str) and REVIEW_TASK_ID.fullmatch(task_id):
            found.add(task_id)
    return found


def analyze(
    repo_root: Path,
    catalog_path: Path,
    queue_path: Path,
    state_path: Path,
    runtime_path: Path,
    existing_issues_path: Path | None = None,
) -> dict:
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
    # Exclude old candidates during discovery; otherwise the bounded first batch
    # is rediscovered forever and issue creation filters every result as duplicate.
    excluded = queued_ids | completed | held | review | catalog_ids | _existing_issue_task_ids(existing_issues_path)
    candidate_groups = []
    for code_rel, test_rel in TARGETS:
        code_path, test_path = repo_root / code_rel, repo_root / test_rel
        # Never follow repository-controlled symlinks while scanning source or tests.
        if code_path.is_symlink() or test_path.is_symlink():
            continue
        if not code_path.is_file() or not test_path.is_file():
            continue
        if not TEST_PATH.fullmatch(test_rel):
            continue
        code_source = code_path.read_text(encoding="utf-8")
        test_source = test_path.read_text(encoding="utf-8")
        referenced_symbols = _referenced_symbols(test_source)
        group = []
        for function, line in _public_functions(code_source):
            leaf = function.rsplit(".", 1)[-1]
            # AST references avoid false "covered" matches in comments and strings.
            # Indirect coverage may still exist, so candidates remain review-only.
            if leaf in referenced_symbols:
                continue
            suffix = hashlib.sha256(f"{code_rel}:{function}".encode()).hexdigest()[:10]
            task_id = f"review-coverage-gap-{suffix}"
            if task_id in excluded:
                continue
            evidence = f"{code_rel}:{line}"
            fingerprint = hashlib.sha256(
                f"{code_rel}\\0{function}\\0{line}\\0{hashlib.sha256(code_source.encode()).hexdigest()}\\0{hashlib.sha256(test_source.encode()).hexdigest()}".encode()
            ).hexdigest()
            group.append({
                "id": task_id,
                "instruction": f"人手レビュー後に限り、{test_rel} に {code_rel} の {function} ({evidence}) の境界条件を検証する新しい回帰テストを1件追加してください。既存テストを変更せず、指定テストファイルのみ変更してください。候補生成はテスト内のAST参照に基づくヒューリスティックのため、間接カバレッジや既存テストとの重複を先に確認してください。外部通信・シークレット・OS操作・マージ・デプロイは禁止。",
                "target_test": test_rel,
                "evidence": evidence,
                "source_function": function,
                "status": "REVIEW_REQUIRED",
                "heuristic": "public-symbol-name-not-found-in-test-ast; may have indirect coverage",
                "fingerprint": fingerprint,
            })
            if len(group) >= MAX_CANDIDATES:
                break
        if group:
            candidate_groups.append(group)

    # Round-robin across allowlisted target pairs so a large early module cannot
    # consume the entire review batch and starve later modules indefinitely.
    candidates = []
    depth = 0
    while len(candidates) < MAX_CANDIDATES:
        added_at_depth = False
        for group in candidate_groups:
            if depth < len(group):
                candidates.append(group[depth])
                added_at_depth = True
                if len(candidates) >= MAX_CANDIDATES:
                    break
        if not added_at_depth:
            break
        depth += 1

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
    parser.add_argument("--existing-issues", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = analyze(args.repo_root, args.catalog, args.queue, args.state, args.runtime, args.existing_issues)
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
