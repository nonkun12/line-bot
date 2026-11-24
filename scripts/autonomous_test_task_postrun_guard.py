"""Fail-closed post-run verifier for run-local test-only admissions."""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from scripts.autonomous_task_target_allowlist import TARGETS

ALLOWED_TEST_PATHS = {test_path for _, test_path in TARGETS}

FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "__import__", "open",
}
FORBIDDEN_ROOTS = {
    "subprocess", "socket", "requests", "urllib", "http", "ftplib",
}
FORBIDDEN_OS_CALLS = {
    "system", "popen", "spawn", "execv", "execve", "remove", "unlink",
}
# Block common escape hatches even when reached through an already-imported
# module or a pathlib object rather than a direct built-in call.
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "__import__", "open", "getattr", "setattr",
    "delattr", "globals", "locals", "vars", "breakpoint", "__builtins__",
}
FORBIDDEN_ATTRIBUTES = {
    "open", "unlink", "rmdir", "mkdir", "makedirs", "removedirs",
    "remove", "rmtree", "write_text", "write_bytes", "touch", "rename",
    "replace", "chmod", "chown", "symlink_to", "hardlink_to", "truncate",
    "system", "popen", "spawn", "execv", "execve", "run", "Popen",
    "connect", "create_connection", "urlopen", "request", "send", "recv",
    "loads", "load", "__globals__", "__builtins__", "__subclasses__",
    "__getattribute__", "__setattr__", "__delattr__",
}


def _function_name(node: ast.AST) -> str | None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    return None


def _reject_unsafe_test_body(function: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    for node in ast.walk(function):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("new_test_must_not_add_imports")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise ValueError("new_test_uses_forbidden_escape_hatch")
        if isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRIBUTES or (
                node.attr.startswith("__") and node.attr.endswith("__")
            ):
                raise ValueError("new_test_uses_forbidden_attribute")
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name) and target.id in FORBIDDEN_CALLS:
                raise ValueError("new_test_uses_forbidden_dynamic_or_file_call")
            if isinstance(target, ast.Attribute):
                if isinstance(target.value, ast.Name):
                    root, attr = target.value.id, target.attr
                    if root in FORBIDDEN_ROOTS:
                        raise ValueError("new_test_uses_forbidden_network_or_process_api")
                    if root == "os" and attr in FORBIDDEN_OS_CALLS:
                        raise ValueError("new_test_uses_forbidden_os_api")


def verify_append_only_test_change(original_text: str, produced_text: str) -> str:
    try:
        before = ast.parse(original_text)
        after = ast.parse(produced_text)
    except SyntaxError as exc:
        raise ValueError("test_file_ast_invalid") from exc

    old_nodes = before.body
    new_nodes = after.body
    # One narrowly allowlisted module-level import is needed by the safe_stock_quote
    # regression test. Imports inside the generated test body remain forbidden.
    allowed_imports = [
        node for node in new_nodes
        if isinstance(node, ast.ImportFrom)
        and node.module == "core.stocks"
        and [(alias.name, alias.asname) for alias in node.names]
        == [("StockQuote", None), ("safe_stock_quote", None)]
    ]
    if len(allowed_imports) > 1:
        raise ValueError("new_test_module_import_not_allowlisted")
    retained_nodes = [node for node in new_nodes if node not in allowed_imports]
    if len(retained_nodes) != len(old_nodes) + 1:
        raise ValueError("change_must_append_exactly_one_top_level_test_function")

    for old, new in zip(old_nodes, retained_nodes[:len(old_nodes)]):
        if ast.dump(old, include_attributes=False) != ast.dump(new, include_attributes=False):
            raise ValueError("existing_test_file_ast_was_modified")

    added = retained_nodes[-1]
    name = _function_name(added)
    if not name or not name.startswith("test_"):
        raise ValueError("appended_node_is_not_a_pytest_test_function")
    _reject_unsafe_test_body(added)
    return name


def _git_text(repo_root: Path, revision: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=repo_root, check=True, capture_output=True, text=True,
    )
    return result.stdout


def verify_policy_run(
    policy: object,
    rows: list[dict[str, Any]],
    repo_root: Path,
    expected_base_sha: str,
) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise ValueError("policy_report_invalid")
    if policy.get("status") != "POLICY_ADMITTED":
        return {"status": "POLICY_GUARD_SKIPPED", "reason": "no_policy_admission"}
    task_id = policy.get("admitted_task_id")
    target = policy.get("admitted_allowed_path")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("admitted_task_id_missing")
    if not isinstance(target, str) or target not in ALLOWED_TEST_PATHS:
        raise ValueError("admitted_test_path_not_allowlisted")
    matching = [row for row in rows if row.get("task_id") == task_id]
    if len(matching) != 1 or len(rows) != 1:
        raise ValueError("policy_task_execution_evidence_missing_or_ambiguous")
    row = matching[0]
    if row.get("status") not in {"PASS", "NO_CHANGE"} or row.get("exit_code") != 0:
        raise ValueError("policy_task_did_not_finish_with_safe_status")
    base_sha = row.get("base_sha")
    produced_sha = row.get("produced_sha")
    if base_sha != expected_base_sha or not isinstance(produced_sha, str):
        raise ValueError("policy_task_sha_evidence_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", produced_sha):
        raise ValueError("policy_task_produced_sha_malformed")
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if head_sha != produced_sha:
        raise ValueError("policy_task_produced_sha_is_not_checked_out_head")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_sha, produced_sha],
        cwd=repo_root, check=True, capture_output=True, text=True,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo_root, check=True, capture_output=True, text=True,
    ).stdout
    allowed_untracked = {
        "artifacts/maintenance-ai/diagnosis.json",
        "artifacts/debug-agent/diagnosis.json",
    }
    unexpected_status = []
    for line in status.splitlines():
        if line.startswith("?? ") and line[3:] in allowed_untracked:
            continue
        unexpected_status.append(line)
    if unexpected_status:
        raise ValueError("policy_task_worktree_not_clean_after_commit")
    subprocess.run(
        ["git", "diff", "--check", base_sha, produced_sha],
        cwd=repo_root, check=True, capture_output=True, text=True,
    )
    diff = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", base_sha, produced_sha],
        cwd=repo_root, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    if row["status"] == "NO_CHANGE":
        if diff or base_sha != produced_sha:
            raise ValueError("no_change_task_produced_unexpected_diff")
        return {"status": "POLICY_GUARD_PASS", "task_id": task_id, "change": "NO_CHANGE"}
    if diff != [target]:
        raise ValueError("policy_task_changed_unexpected_paths_or_multiple_files")
    before = _git_text(repo_root, base_sha, target)
    after = _git_text(repo_root, produced_sha, target)
    function_name = verify_append_only_test_change(before, after)
    return {
        "status": "POLICY_GUARD_PASS",
        "task_id": task_id,
        "change": "APPENDED_ONE_TEST",
        "test_function": function_name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--policy-report", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    try:
        policy = json.loads(args.policy_report.read_text(encoding="utf-8"))
        rows = []
        for line in args.results.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("task_result_row_invalid")
                rows.append(item)
        result = verify_policy_run(policy, rows, args.repo_root, args.base_sha)
    except (OSError, UnicodeError, json.JSONDecodeError, subprocess.CalledProcessError, ValueError) as exc:
        print("AUTONOMOUS_TEST_POSTRUN_BLOCKED: " + str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
