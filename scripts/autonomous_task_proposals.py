"""Generate reviewed task proposals and bounded, test-only autonomous fallback work.

Issue-derived tasks require an explicit approval label. When the curated queue is
empty, one deterministic test-only task may be queued from discovered test files only.
The target-content fingerprint prevents repeating an unchanged NO_CHANGE task;
all generated work remains bounded and cannot edit production source.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
TEST_PATH = re.compile(r"^(tests|uhip/tests)/test_[A-Za-z0-9_]+\.py$")
SPEC_MARKER = "<!-- autonomous-task-spec -->"
AUTO_TASK_ID = re.compile(r"^(auto-test-[a-z0-9-]+)-([0-9a-f]{12})$")


def _object(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("invalid proposal input") from exc
    if not isinstance(value, (dict, list)):
        raise ValueError("proposal input must be an object or list")
    return value


def _spec(body: str) -> dict | None:
    if not isinstance(body, str) or body.count(SPEC_MARKER) != 2:
        return None
    _, payload, _ = body.split(SPEC_MARKER)
    try:
        spec = json.loads(payload.strip())
    except ValueError:
        return None
    if not isinstance(spec, dict):
        return None
    task_id = spec.get("id")
    instruction = spec.get("instruction")
    paths = spec.get("allowed_paths")
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        return None
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 2000:
        return None
    if not isinstance(paths, list) or not paths or len(paths) > 3:
        return None
    if any(not isinstance(p, str) or not TEST_PATH.fullmatch(p) for p in paths):
        return None
    return {"id": task_id, "instruction": instruction.strip(), "allowed_paths": paths}


def _auto_test_task_for_path(repo_root: Path, path: Path) -> dict | None:
    """Build one catalog definition from a real, repository-contained test file."""
    root = repo_root.resolve()
    try:
        candidate = path.resolve()
        relative = candidate.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None
    if not TEST_PATH.fullmatch(relative):
        return None
    path_slug = re.sub(
        r"[^a-z0-9-]+", "-", Path(relative).with_suffix("").as_posix().lower()
    ).strip("-")
    task_prefix = f"auto-test-{path_slug}-"
    try:
        target_content = candidate.read_bytes()
    except OSError:
        return None
    fingerprint = hashlib.sha256(target_content).hexdigest()
    task_id = f"{task_prefix}{fingerprint[:12]}"
    if not TASK_ID.fullmatch(task_id):
        return None
    instruction = (
        f"Review existing tests in {relative} and read related implementation files "
        "for context, but edit only this one allowed test file. Append exactly one focused, "
        "non-duplicate regression test for a concrete uncovered edge case. Do not edit, delete, "
        "rename, or reformat any existing line. Do not add imports; use only names already "
        "available in the file and Python builtins. Do not repair an existing failing test; report "
        "the failure and return NO_CHANGE instead. Use dummy or temporary data only, and do not "
        "access the host filesystem, environment, or network. If no clear "
        "uncovered behavior can be tested without guessing, make no change and report NO_CHANGE. "
        "Do not change implementation, configuration, "
        "workflow, dependency, or secret files. No network/external service access, no secrets, "
        "no OS/UI actions, no merge, and no deploy. Run the narrow test and report its evidence."
    )
    return {"id": task_id, "instruction": instruction, "allowed_paths": [relative]}


def build_auto_test_catalog(repo_root: Path) -> list[dict]:
    """Return trusted, deterministic registrations for discovered test files."""
    root = repo_root.resolve()
    paths = sorted(
        [*root.glob("tests/test_*.py"), *root.glob("uhip/tests/test_*.py")],
        key=lambda path: path.as_posix(),
    )
    definitions = []
    seen_ids = set()
    for path in paths:
        task = _auto_test_task_for_path(root, path)
        if task is None:
            continue
        if task["id"] in seen_ids:
            raise ValueError("duplicate generated auto-test task ID")
        seen_ids.add(task["id"])
        definitions.append(task)
    return definitions


def validate_auto_test_diff(diff_text: str) -> tuple[bool, str]:
    """Allow one additive test function with no imports or risky host access."""
    if not isinstance(diff_text, str) or not diff_text.strip():
        return False, "empty_diff"
    lines = diff_text.splitlines()
    if any(line.startswith("-") and not line.startswith("---") for line in lines):
        return False, "existing_lines_modified"

    added = [
        line[1:]
        for line in lines
        if line.startswith("+") and not line.startswith("+++")
    ]
    code = [line for line in added if line.strip()]
    added_function_names = re.findall(
        r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        "\n".join(code),
        flags=re.MULTILINE,
    )
    if (
        len(added_function_names) != 1
        or not added_function_names[0].startswith("test_")
        or not code
        or not re.fullmatch(
            r"(?:async\s+)?def\s+test_[A-Za-z0-9_]+\s*\(.*", code[0].strip()
        )
    ):
        return False, "expected_exactly_one_new_test_function"
    if any(not line[:1].isspace() for line in code[1:]):
        return False, "module_level_addition_rejected"
    try:
        tree = ast.parse("\n".join(added))
    except SyntaxError:
        return False, "invalid_added_test_syntax"
    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False, "expected_exactly_one_new_test_function"
    if not tree.body[0].name.startswith("test_"):
        return False, "expected_exactly_one_new_test_function"

    # Require a direct, reachable check in the test body. Nested assertions are
    # not evidence: they may be hidden in dead branches or never-called helpers.
    test_function = tree.body[0]
    if any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in {"skip", "skipif", "xfail"})
            or (isinstance(node.func, ast.Attribute) and node.func.attr in {"skip", "skipif", "xfail"})
        )
        for node in ast.walk(test_function)
    ):
        return False, "test_skip_or_xfail_rejected"

    def _trivial_assertion(expr: ast.expr) -> bool:
        if isinstance(expr, ast.Constant):
            return True
        if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.Or):
            return any(
                isinstance(value, ast.Constant) and bool(value.value)
                for value in expr.values
            )
        if isinstance(expr, ast.Compare):
            operands = [expr.left, *expr.comparators]
            if len(expr.ops) == 1 and isinstance(expr.ops[0], (ast.Eq, ast.Is)):
                if ast.dump(operands[0], include_attributes=False) == ast.dump(operands[1], include_attributes=False):
                    return True
                if all(isinstance(item, ast.Constant) for item in operands):
                    left, right = operands[0].value, operands[1].value
                    if type(left) is type(right) and expr.ops[0].__class__ in (ast.Eq, ast.Is):
                        return left == right
        return False

    direct_checks = []
    for statement in test_function.body:
        if isinstance(statement, (ast.Return, ast.Raise)):
            return False, "test_exits_before_assertion"
        if isinstance(statement, ast.Assert):
            direct_checks.append(("assert", statement.test))
        elif isinstance(statement, ast.With):
            is_raises = bool(statement.items) and all(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and isinstance(item.context_expr.func.value, ast.Name)
                and item.context_expr.func.value.id == "pytest"
                and item.context_expr.func.attr == "raises"
                for item in statement.items
            )
            if is_raises:
                direct_checks.append(("raises", None))

    if not direct_checks:
        return False, "test_has_no_assertion"
    if any(kind == "assert" and _trivial_assertion(expr) for kind, expr in direct_checks):
        return False, "test_assertion_is_trivial"

    forbidden_names = {
        "os", "sys", "subprocess", "socket", "requests", "urllib", "httpx",
        "http", "aiohttp", "ftplib", "smtplib", "websocket", "shutil", "pathlib",
        "importlib", "ctypes", "builtins", "eval", "exec", "compile", "open",
        "__import__", "__builtins__", "getattr", "setattr", "delattr", "globals", "locals", "vars",
        "dir", "type", "object", "memoryview", "breakpoint", "input", "help",
        "GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN",
    }
    forbidden_attributes = {
        "environ", "getenv", "system", "popen", "spawn", "execv", "execve",
        "urlopen", "create_connection", "unlink", "rmtree", "remove", "home",
        "cwd", "expanduser", "__globals__", "__builtins__", "__subclasses__", "__dict__",
        "__class__", "__base__", "__mro__", "__getattribute__", "__getattr__", "__code__",
        "__closure__", "__self__", "__func__", "__reduce__", "__reduce_ex__",
        # Reflection helpers and dynamic code execution are forbidden even when
        # reached through an alias such as an existing builtins import.
        "getattr", "setattr", "delattr", "eval", "exec", "compile", "__import__",
        "breakpoint", "input", "help", "vars", "globals", "locals",
        # Generated tests are not permitted to read/write repository or host files.
        "open", "read_text", "read_bytes", "write_text", "write_bytes", "readlink",
        "iterdir", "glob", "rglob", "resolve", "absolute", "relative_to", "with_name",
        "with_suffix", "mkdir", "touch", "stat", "lstat", "chmod", "chown", "rename",
        "replace", "symlink_to", "hardlink_to", "walk", "listdir", "scandir", "access",
        "exists", "is_file", "is_dir", "is_symlink", "samefile", "read", "write",
        "get", "post", "put", "patch", "delete", "request", "connect", "create_connection",
        "send", "recv", "execute", "executemany", "commit", "rollback",
        # Process-launch APIs can be reached through an existing aliased import.
        "run", "Popen", "call", "check_call", "check_output", "fork", "spawn",
        "execv", "execve", "execvp", "execvpe", "startfile", "kill", "killpg",
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return False, "imports_rejected"
        if isinstance(node, ast.Name) and node.id in forbidden_names:
            return False, "host_access_rejected"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if (
                re.match(r"^(?:/|~[\\/])", node.value)
                or "__" in node.value
                or node.value.lower() in {
                    "getattr", "setattr", "delattr", "globals", "locals", "vars",
                    "eval", "exec", "open", "compile", "environ", "getenv",
                    "system", "popen", "import", "os", "sys", "builtins",
                }
            ):
                return False, "host_access_rejected"
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
            return False, "host_access_rejected"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden_names:
            return False, "host_access_rejected"
    return True, "ok"


def _auto_test_task(
    repo_root: Path,
    excluded: set[str],
    blocked_target_prefixes: set[str],
) -> dict | None:
    """Select one discovered test task while preserving completion and HOLD state."""
    for task in build_auto_test_catalog(repo_root):
        task_prefix = task["id"].rsplit("-", 1)[0] + "-"
        if task_prefix in blocked_target_prefixes or task["id"] in excluded:
            continue
        return task
    return None


def build_proposals(
    issues_path: Path,
    queue_path: Path,
    state_path: Path,
    output_path: Path,
    *,
    enable_auto_refill: bool = False,
    repo_root: Path | None = None,
) -> dict:
    issues = _object(issues_path)
    queue = _object(queue_path)
    state = _object(state_path)
    if not isinstance(issues, list) or not isinstance(queue, dict) or not isinstance(state, dict):
        raise ValueError("invalid proposal input schema")
    queued = queue.get("tasks")
    completed = state.get("completed", [])
    recovery = state.get("recovery_ai")
    if not isinstance(queued, list) or not isinstance(completed, list) or not all(isinstance(x, str) for x in completed):
        raise ValueError("invalid queue or completion state")
    if not isinstance(recovery, dict) or type(recovery.get("schema_version")) is not int or recovery.get("schema_version") != 1 or not isinstance(recovery.get("tasks"), dict) or "checkpoint" not in recovery:
        raise ValueError("Recovery AI state is invalid")

    excluded = {x.get("id") for x in queued if isinstance(x, dict) and isinstance(x.get("id"), str)} | set(completed)
    recovery_tasks = recovery["tasks"]
    blocked_task_ids: set[str] = set()
    blocked_auto_target_prefixes: set[str] = {
        match.group(1) + "-"
        for task_id in completed
        if isinstance(task_id, str)
        and (match := AUTO_TASK_ID.fullmatch(task_id)) is not None
    }
    pruned_task_ids: list[str] = []
    for task_id, record in recovery_tasks.items():
        if not isinstance(task_id, str) or not isinstance(record, dict):
            raise ValueError("Recovery AI task record is invalid")
        held = record.get("held", False)
        resume_requires_review = record.get("resume_requires_review", False)
        if type(held) is not bool or type(resume_requires_review) is not bool:
            raise ValueError("Recovery AI task flags are invalid")
        if held or resume_requires_review:
            excluded.add(task_id)
            blocked_task_ids.add(task_id)
            match = AUTO_TASK_ID.fullmatch(task_id)
            if match:
                blocked_auto_target_prefixes.add(match.group(1) + "-")

        success_evidence = record.get("last_success_evidence")
        if success_evidence is not None:
            if (
                not isinstance(success_evidence, dict)
                or success_evidence.get("task_id") != task_id
                or success_evidence.get("status") not in {"PASS", "NO_CHANGE"}
            ):
                raise ValueError("Recovery AI success evidence is invalid")
            # A successful execution that never reached the durable completed
            # list (for example, because publishing was rejected) needs review;
            # do not spin on the same file fingerprint next schedule.
            if task_id not in completed:
                excluded.add(task_id)
                blocked_task_ids.add(task_id)
                match = AUTO_TASK_ID.fullmatch(task_id)
                if match:
                    blocked_auto_target_prefixes.add(match.group(1) + "-")

    active_queue = []
    for item in queued:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("queued task is invalid")
        task_id = item["id"]
        match = AUTO_TASK_ID.fullmatch(task_id)
        blocked_by_prefix = match is not None and match.group(1) + "-" in blocked_auto_target_prefixes
        if task_id in completed or task_id in blocked_task_ids or blocked_by_prefix:
            pruned_task_ids.append(task_id)
            continue
        active_queue.append(item)
    if pruned_task_ids:
        queue["tasks"] = active_queue
        queued = active_queue

    proposals = []
    approved_tasks = []
    seen = set()
    max_tasks = queue.get("max_tasks_per_run", 4)
    if type(max_tasks) is not int or not 1 <= max_tasks <= 4:
        raise ValueError("invalid runtime task limit")
    queue_capacity = max(0, max_tasks - len(queued))
    for issue in issues[:100]:
        if not isinstance(issue, dict):
            raise ValueError("issue record is invalid")
        labels = issue.get("labels", [])
        if not isinstance(labels, list):
            raise ValueError("issue labels are invalid")
        label_names = {label.get("name") for label in labels if isinstance(label, dict)}
        if issue.get("state") != "open":
            continue
        approved = "autonomous-task-approved" in label_names
        candidate = "autonomous-task-candidate" in label_names
        if not approved and not candidate:
            continue
        spec = _spec(issue.get("body", ""))
        if spec is None or spec["id"] in excluded or spec["id"] in seen:
            continue
        number = issue.get("number")
        if type(number) is not int or number < 1:
            continue
        seen.add(spec["id"])
        fingerprint = hashlib.sha256(
            json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if approved:
            if len(approved_tasks) < min(4, queue_capacity):
                approved_tasks.append({**spec, "source_issue": number, "proposal_fingerprint": fingerprint})
                excluded.add(spec["id"])
            continue
        proposals.append({
            **spec,
            "source_issue": number,
            "status": "REVIEW_REQUIRED",
            "proposal_fingerprint": fingerprint,
        })
        if len(proposals) >= 4:
            break

    # Never inject fallback work ahead of an existing curated/approved queue.
    # At most one test-only task is added from discovered, strictly allowlisted files.
    auto_task = None
    if enable_auto_refill and not queued and not approved_tasks and queue_capacity > 0:
        auto_task = _auto_test_task(
            repo_root or Path.cwd(),
            excluded | seen,
            blocked_auto_target_prefixes,
        )
        if auto_task is not None:
            approved_tasks.append(auto_task)

    if approved_tasks or pruned_task_ids:
        updated_queue = dict(queue)
        updated_queue["tasks"] = [*queued, *approved_tasks]
        queue_path.write_text(json.dumps(updated_queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if auto_task is not None and proposals:
        status = "AUTO_QUEUED_AND_REVIEW_REQUIRED"
    elif auto_task is not None:
        status = "AUTO_QUEUED"
    elif approved_tasks and proposals:
        status = "QUEUED_APPROVED_AND_REVIEW_REQUIRED"
    elif approved_tasks:
        status = "QUEUED_APPROVED"
    elif proposals:
        status = "REVIEW_REQUIRED"
    elif enable_auto_refill and not queued and not approved_tasks:
        status = "AUTO_REFILL_EXHAUSTED"
    else:
        status = "NO_TRUSTED_CANDIDATES"
    result = {
        "version": 1,
        "status": status,
        "approved_count": len(approved_tasks) if auto_task is None else 0,
        "approved_task_ids": [task["id"] for task in approved_tasks] if auto_task is None else [],
        "auto_queued_count": 1 if auto_task is not None else 0,
        "auto_queued_task_ids": [auto_task["id"]] if auto_task is not None else [],
        "pruned_task_ids": pruned_task_ids,
        "proposal_count": len(proposals),
        "proposals": proposals,
        "reason": (
            "no_eligible_test_target"
            if enable_auto_refill and auto_task is None and not queued and not approved_tasks
            else (None if approved_tasks or proposals else "no_open_labeled_issue_with_valid_test_only_spec")
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def auto_test_refill_policy_enabled(catalog: object) -> bool:
    """Require the repository's versioned catalog to opt into exactly one safe task."""
    if (
        not isinstance(catalog, dict)
        or type(catalog.get("version")) is not int
        or catalog.get("version") != 1
        or not isinstance(catalog.get("tasks"), list)
    ):
        return False
    policy = catalog.get("auto_test_refill")
    if not isinstance(policy, dict):
        return False
    return (
        policy.get("enabled") is True
        and type(policy.get("max_tasks_per_run")) is int
        and policy.get("max_tasks_per_run") == 1
        and policy.get("allowed_roots") == ["tests", "uhip/tests"]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--enable-auto-refill", action="store_true")
    args = parser.parse_args()
    try:
        if args.enable_auto_refill:
            if args.catalog is None:
                raise ValueError("versioned auto-refill catalog is required")
            catalog = _object(args.catalog)
            if not auto_test_refill_policy_enabled(catalog):
                raise ValueError("versioned auto-refill policy is not enabled")
        result = build_proposals(
            args.issues, args.queue, args.state, args.output,
            enable_auto_refill=args.enable_auto_refill,
            repo_root=args.repo_root,
        )
    except (ValueError, OSError) as exc:
        print("TASK_PROPOSALS_BLOCKED: " + type(exc).__name__)
        return 2
    print(json.dumps({
        "status": result["status"],
        "proposal_count": result["proposal_count"],
        "auto_queued_count": result["auto_queued_count"],
        "reason": result["reason"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
