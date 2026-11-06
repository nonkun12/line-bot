"""Guarded LINE development worker v2.

AI proposes structured search/replace operations instead of raw unified diffs.
Python validates the operations, applies guarded tests, and opens a PR.
Security-sensitive files are never editable by this worker.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import traceback
from functools import lru_cache
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from groq import Groq

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.self_improvement_policy import SelfImprovementDecision, assess_self_improvement

ROOT = _ROOT
MODEL = os.environ.get("DEV_AI_MODEL", "openai/gpt-oss-20b")
MAX_FILES = 1
MAX_FILE_CHARS = 12000
# Groq's 8,000 TPM limit counts prompt plus requested completion tokens.
# A 3,500-token completion plus the observed ~4,808-token prompt was rejected
# at 8,308 TPM. Keep the default completion budget at 2,500 to leave headroom.
MAX_RESPONSE_TOKENS = 2500
# The append-only prompt is independently bounded to 3,000 context chars.
# The previous 2,500-token completion cap exhausted GPT-OSS reasoning before
# it emitted a test function. A 4,000-token budget remains below the observed
# 8,000 TPM ceiling for this bounded prompt; do not increase the context cap
# alongside it without re-evaluating the combined token budget.
MAX_APPEND_ONLY_RESPONSE_TOKENS = 4000
MAX_APPEND_ONLY_CONTEXT_CHARS = 3000
MAX_INSTRUCTION_LENGTH = 2000
MAX_REPAIR_ATTEMPTS = 1
MAX_APPLY_REPAIR_ATTEMPTS = 2
MAX_PLAN_REPAIR_ATTEMPTS = 2
ALLOWED_SUFFIXES = (".py", ".md", ".json", ".txt")
PROTECTED_PATHS = {
    ".github", ".env", "config.py",
    "scripts/line_development_worker.py",
    "scripts/line_development_worker_safe.py",
    "scripts/line_development_worker_v2.py",
    "core/line_development_runtime.py",
    "scripts/run_minimal_autonomous_loop.py",
    "scripts/run_guarded_runtime.py",
    "tests/test_minimal_autonomous_loop.py",
    "line_development.py",
    "git_safety.py", "patch_validator.py", "render_client.py",
}
PROTECTED_PREFIXES = (".github/", "secrets/", ".git/")
_COMMENT_TEST_PATH = "line_development.py"
_COMMENT_TEST_PATH_ALIASES = {"scripts/line_development.py", "./scripts/line_development.py"}
_EXPLICIT_PATH_PATTERN = re.compile(r"[\w][\w\-./]*\.(?:py|md|json|txt)", re.IGNORECASE)
_COMMENT_REQUEST_PATTERN = re.compile(r"コメント.*(?:1行|一行)|(?:1行|一行).*コメント", re.IGNORECASE | re.DOTALL)
_TEST_INSTRUCTION_PATTERN = re.compile(r"(?:workflow|connection)[\s_-]*test", re.IGNORECASE)
_TEST_INSTRUCTION_EXACT = {"開発接続テスト", "接続テスト", "動作確認", "疎通確認", "LINE自動開発テスト"}


def run(cmd: list[str], timeout: int = 900, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, input=input_text, capture_output=True, timeout=timeout)


def is_protected(path: str) -> bool:
    return path in PROTECTED_PATHS or any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def is_test_path(path: str) -> bool:
    """Recognize pytest files in root, nested test directories, and conftest modules."""
    normalized = str(path or "").replace("\\", "/").strip("/")
    parts = normalized.split("/") if normalized else []
    name = parts[-1] if parts else ""
    return (
        "tests" in parts[:-1]
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


@lru_cache(maxsize=512)
def _shared_policy_decision(path: str) -> SelfImprovementDecision:
    return assess_self_improvement((path,)).decision


def _is_shared_policy_autonomous(path: str) -> bool:
    return _shared_policy_decision(path) is SelfImprovementDecision.AUTONOMOUS_REVIEW


def _autonomous_allowed_path_manifest() -> set[str] | None:
    """Parse the per-task edit scope; malformed manifests fail closed."""
    raw = os.environ.get("AUTONOMOUS_ALLOWED_PATHS")
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise RuntimeError("AUTONOMOUS_ALLOWED_PATHS is invalid") from None
    if not isinstance(value, list) or not value:
        raise RuntimeError("AUTONOMOUS_ALLOWED_PATHS is invalid")

    paths: set[str] = set()
    for item in value:
        if (
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or item.startswith("/")
            or "\\" in item
            or any(char in item for char in ("\n", "\r", "\x00"))
            or re.match(r"^[A-Za-z]:", item)
            or any(part in {"", ".", ".."} for part in item.split("/"))
        ):
            raise RuntimeError("AUTONOMOUS_ALLOWED_PATHS is invalid")
        paths.add(item)
    return paths


def repo_files() -> list[str]:
    proc = run(["git", "ls-files"])
    if proc.returncode != 0:
        raise RuntimeError("git ls-files failed")
    tracked = [p for p in proc.stdout.splitlines() if p]
    allowed_paths = _autonomous_allowed_path_manifest()
    if allowed_paths is not None:
        # Exact tracked-path membership is required: no globs, traversal,
        # untracked files, or expansion to neighboring source files.
        if not allowed_paths.issubset(set(tracked)):
            raise RuntimeError("AUTONOMOUS_ALLOWED_PATHS references untracked files")
        for path in allowed_paths:
            if is_protected(path) or not _is_shared_policy_autonomous(path):
                raise RuntimeError("AUTONOMOUS_ALLOWED_PATHS contains a protected file")
    return [
        p
        for p in tracked
        if (allowed_paths is None or p in allowed_paths)
        and p.endswith(ALLOWED_SUFFIXES)
        and not is_protected(p)
        and _is_shared_policy_autonomous(p)
    ]


def ask(client: Groq, system: str, user: str, max_tokens: int = MAX_RESPONSE_TOKENS) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_completion_tokens=max_tokens,
        reasoning_effort=os.environ.get("DEV_AI_REASONING_EFFORT", "low"),
        include_reasoning=False,
    )
    return response.choices[0].message.content or ""

def ask_text(client: Groq, system: str, user: str, max_tokens: int = MAX_RESPONSE_TOKENS) -> str:
    """Request bounded plain text without enabling the provider's JSON mode."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_completion_tokens=max_tokens,
        reasoning_effort=os.environ.get("DEV_AI_REASONING_EFFORT", "low"),
        include_reasoning=False,
    )
    return response.choices[0].message.content or ""


def is_test_instruction(instruction: str) -> bool:
    normalized = str(instruction or "").strip()
    return normalized in _TEST_INSTRUCTION_EXACT or bool(_TEST_INSTRUCTION_PATTERN.fullmatch(normalized))


def _extract_explicit_path(instruction: str, files: list[str]) -> str | None:
    allowed = set(files)
    candidates: set[str] = set()
    for match in _EXPLICIT_PATH_PATTERN.finditer(instruction):
        token = match.group(0).strip("`'\"()[]{}<> 　").lstrip("./")
        if token in _COMMENT_TEST_PATH_ALIASES:
            token = _COMMENT_TEST_PATH
        if token == _COMMENT_TEST_PATH and (ROOT / _COMMENT_TEST_PATH).is_file():
            candidates.add(token)
            continue
        if token in allowed and _is_shared_policy_autonomous(token):
            candidates.add(token)
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


_E2E_TEST_KEYWORDS = (
    "E2E",
    "e2e",
    "疎通テスト",
    "接続テスト",
    "開発テスト",
    "自動開発テスト",
    # Operational validation requests must use the dedicated E2E harness,
    # not the generic implementation-file selector.
    "実運用テスト",
    "実運用検証",
    "基盤検証",
)

_E2E_TEST_TARGETS = (
    "tests/test_line_development.py",
    "tests/test_app_development_dispatch.py",
)


def choose_file(client: Groq, instruction: str, files: list[str]) -> str | None:
    explicit = _extract_explicit_path(instruction, files)
    if explicit:
        return explicit

    if any(keyword in instruction for keyword in _E2E_TEST_KEYWORDS):
        for candidate in _E2E_TEST_TARGETS:
            if candidate in files:
                return candidate

    # Generic implementation requests must not be steered into tests. Explicit
    # test paths and the dedicated E2E targets above remain available.
    candidates = [path for path in files if not is_test_path(path)]
    if not candidates:
        return None
    prompt = f"Instruction:\n{instruction}\n\nEligible files:\n" + "\n".join(candidates)
    try:
        data = parse_plan(ask(client, "Select exactly one eligible file and return JSON only: {\"file\":\"path\"} or {\"file\":null}", prompt))
    except Exception as exc:
        print(f"[FILE-SELECTION] model selection failed: {type(exc).__name__}", flush=True)
        return None
    chosen = data.get("file")
    if isinstance(chosen, str) and chosen in candidates and _is_shared_policy_autonomous(chosen):
        return chosen
    return None


def parse_plan(text: str) -> dict:
    clean = str(text or "").strip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError as original_error:
        data = None
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, re.IGNORECASE | re.DOTALL)
        if fenced:
            try:
                data = json.loads(fenced.group(1))
            except json.JSONDecodeError:
                data = None
        if data is None:
            decoder = json.JSONDecoder()
            for match in re.finditer(r"\{", clean):
                try:
                    candidate, _ = decoder.raw_decode(clean[match.start():])
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict):
                    data = candidate
                    break
        if data is None:
            raise original_error
    if not isinstance(data, dict):
        raise ValueError("plan must be object")
    return data


def context_for(path: str) -> str:
    """Keep context within the character budget while retaining both file ends."""
    target = ROOT / path
    content = target.read_text(encoding="utf-8")
    if len(content) <= MAX_FILE_CHARS:
        return content

    marker = "\n...[middle omitted; context bounded]...\n"
    budget = MAX_FILE_CHARS - len(marker)
    head_size = budget // 2
    tail_size = budget - head_size
    return content[:head_size] + marker + content[-tail_size:]


def repair_anchor_plan(
    client: Groq,
    instruction: str,
    chosen: str,
    context: str,
    rejected_plan: dict,
    anchor_error: str,
) -> dict:
    """Perform one bounded repair when the chosen old text is not unique."""
    rejected = json.dumps(rejected_plan, ensure_ascii=False)
    system = '''Repair ONE rejected JSON search/replace plan. Return JSON only.
Keep the same file and requested intent. Re-read the supplied current file context.
The old value MUST be an exact substring that occurs exactly once in the current file.
Choose a distinctive multi-line anchor near the intended edit, preferably including a unique
test/function name and nearby lines. Do not use a generic single line such as "}," or a common
dictionary fragment when a more specific anchor is available.
The new field is replacement text only: no unified-diff markers or markdown fences.
Do not broaden the requested change. If a unique safe anchor cannot be identified, return
{"no_change":true}.'''
    prompt = (
        f"Instruction:\n{instruction}\n\nSelected file:\n{chosen}"
        f"\n\nCurrent file context:\n{context}"
        f"\n\nApply error:\n{anchor_error}"
        f"\n\nRejected plan:\n{rejected}"
    )
    return parse_plan(ask(client, system, prompt, max_tokens=MAX_RESPONSE_TOKENS))


def repair_size_plan(
    client: Groq,
    instruction: str,
    chosen: str,
    context: str,
    rejected_plan: dict,
    size_error: str,
) -> dict:
    """Perform one bounded repair when a replacement is too large."""
    rejected = json.dumps(rejected_plan, ensure_ascii=False)
    system = '''Repair ONE rejected JSON search/replace plan. Return JSON only.
Keep the same file and requested intent. Re-read the supplied current file context.
Make the smallest possible edit. Use one distinctive, short anchor and one short replacement.
The old value must be an exact substring of the current context. The new value must contain only
the replacement text, never a full-file rewrite, unified-diff markers, or markdown fences.
Stay below the worker's existing size limits. Do not broaden the requested change.
If the requested change cannot be expressed as a small safe search/replace, return {"no_change":true}.'''
    prompt = (
        f"Instruction:\n{instruction}\n\nSelected file:\n{chosen}"
        f"\n\nCurrent file context:\n{context}"
        f"\n\nSize validation error:\n{size_error}"
        f"\n\nRejected plan:\n{rejected}"
    )
    return parse_plan(ask(client, system, prompt, max_tokens=MAX_RESPONSE_TOKENS))


def repair_existing_test_modified_plan(
    client: Groq,
    instruction: str,
    chosen: str,
    context: str,
    rejected_plan: dict,
) -> dict:
    """Regenerate one test-only plan as a strictly additive test insertion."""
    rejected = json.dumps(rejected_plan, ensure_ascii=False)
    system = '''Repair ONE rejected test-file plan. Return JSON only.
The selected file is the ONLY file that may change. Add exactly ONE new pytest test function.
Do not edit, rename, delete, reorder, or weaken any existing test function, assertion,
fixture, parametrization, or class. Preserve all existing test definitions byte-for-byte
at the AST level. Prefer appending the new test at the end of the current file.
Return one search/replace change with an exact, unique old anchor from the supplied current
file and a new value that preserves that anchor verbatim and appends only the new test.
Do not rewrite the full file, modify imports or fixtures, change production code, or use
diff markers or markdown fences. If this cannot be done safely, return {"no_change":true}.'''
    prompt = (
        f"Instruction:\n{instruction}\n\nSelected file (ONLY editable file):\n{chosen}"
        f"\n\nCurrent file context:\n{context}"
        f"\n\nRejected validation reason: existing_test_modified"
        f"\n\nRejected plan:\n{rejected}"
    )
    return parse_plan(ask(client, system, prompt, max_tokens=MAX_RESPONSE_TOKENS))


def _test_definition_signatures(source: str, path: str) -> list[str] | None:
    """Return AST signatures for all pytest test functions, including class methods."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return None
    signatures = []

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test"):
                signatures.append(ast.dump(child, include_attributes=False))
            visit(child)

    visit(tree)
    return signatures


def _adds_exactly_one_test(path: str, old: str, new: str) -> bool:
    """Require exactly one new test and byte-for-byte-equivalent ASTs for existing tests."""
    target = ROOT / path
    try:
        original = target.read_text(encoding="utf-8")
        if not old or original.count(old) != 1:
            return False
        candidate = original.replace(old, new, 1)
    except OSError:
        return False
    before = _test_definition_signatures(original, path)
    after = _test_definition_signatures(candidate, path)
    if before is None or after is None or len(after) != len(before) + 1:
        return False
    remaining = list(after)
    for signature in before:
        try:
            remaining.remove(signature)
        except ValueError:
            return False
    return len(remaining) == 1


def _salvage_additive_test_plan(path: str, rejected_plan: dict) -> dict | None:
    """Extract one new top-level test from a rejected rewrite and append it safely.

    The model may return a replacement that rewrites existing tests while adding
    the requested regression. Never keep that replacement. Extract only one new
    test function, then build a fresh append-only patch against the current file.
    """
    if not is_test_path(path) or not path.endswith(".py"):
        return None
    changes = rejected_plan.get("changes")
    if not isinstance(changes, list) or len(changes) != 1:
        return None
    change = changes[0]
    if not isinstance(change, dict) or change.get("file") != path:
        return None
    old, new = change.get("old"), change.get("new")
    if not isinstance(old, str) or not old or not isinstance(new, str):
        return None

    target = ROOT / path
    try:
        original = target.read_text(encoding="utf-8")
        if original.count(old) != 1:
            return None
        candidate = original.replace(old, new, 1)
        original_tree = ast.parse(original, filename=path)
        candidate_tree = ast.parse(candidate, filename=path)
    except (OSError, SyntaxError, ValueError):
        return None

    original_names = {
        node.name for node in original_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    }
    candidate_tests = [
        node for node in candidate_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    ]
    candidate_names = [node.name for node in candidate_tests]
    if (
        not original_names.issubset(set(candidate_names))
        or len(candidate_names) != len(set(candidate_names))
    ):
        return None
    additions = [node for node in candidate_tests if node.name not in original_names]
    if len(additions) != 1:
        return None

    added = additions[0]
    start_line = min(
        [added.lineno, *(decorator.lineno for decorator in added.decorator_list)]
    )
    if added.end_lineno is None:
        return None
    candidate_lines = candidate.splitlines(keepends=True)
    addition = "".join(candidate_lines[start_line - 1 : added.end_lineno]).strip("\r\n")
    if not addition or len(addition) > 1200:
        return None
    addition += "\n"

    original_lines = original.splitlines(keepends=True)
    for start in range(len(original_lines) - 1, -1, -1):
        anchor = "".join(original_lines[start:])
        if len(anchor) > 1200:
            break
        if not anchor.strip() or original.count(anchor) != 1:
            continue
        replacement = anchor.rstrip("\r\n") + "\n\n" + addition
        if len(replacement) > 1800:
            continue
        plan = {
            "no_change": False,
            "changes": [{"file": path, "old": anchor, "new": replacement}],
        }
        valid, detail = validate_plan(plan, path)
        if (
            valid
            and detail != "no_change"
            and _adds_exactly_one_test(path, anchor, replacement)
        ):
            return plan
    return None




def _safe_api_error_detail(exc: Exception) -> str:
    """Expose bounded provider error metadata without leaking credentials or prompts."""
    parts: list[str] = []
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        parts.append(f"status={status}")
    body = getattr(exc, "body", None)
    provider_error = body.get("error", body) if isinstance(body, dict) else {}
    for key in ("code", "param"):
        value = getattr(exc, key, None)
        if not isinstance(value, str) and isinstance(provider_error, dict):
            value = provider_error.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
            parts.append(f"{key}={value}")
    failed_generation = (
        provider_error.get("failed_generation")
        if isinstance(provider_error, dict)
        else None
    )
    if isinstance(failed_generation, str) and failed_generation:
        safe_failure = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", failed_generation)
        safe_failure = re.sub(r"\b(?:gsk[_-]|sk-)[A-Za-z0-9_-]{8,}\b", "[REDACTED]", safe_failure)
        safe_failure = re.sub(
            r"(?i)(api[_ -]?key|token|secret)(\s*[:=]\s*)[^\s,;]+",
            r"\1\2[REDACTED]",
            safe_failure,
        )
        safe_failure = re.sub(r"[\r\n\t]+", " ", safe_failure)
        safe_failure = re.sub(r"\s{2,}", " ", safe_failure).strip()
        if safe_failure:
            parts.append(f"failed_generation={safe_failure[:160]}")
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        for header, label in (
            ("x-request-id", "request_id"),
            ("request-id", "request_id"),
            ("x-groq-region", "region"),
        ):
            try:
                value = headers.get(header)
            except Exception:
                value = None
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value):
                if not any(part.startswith(f"{label}=") for part in parts):
                    parts.append(f"{label}={value}")
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message:
        safe = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", message)
        safe = re.sub(r"\b(?:gsk|sk)-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", safe)
        safe = re.sub(r"[\r\n\t]+", " ", safe)
        safe = re.sub(r"\s{2,}", " ", safe).strip()
        if safe:
            parts.append(f"message={safe[:180]}")
    return ":".join(parts)


def build_append_only_test_plan(
    client: Groq,
    instruction: str,
    chosen: str,
    context: str,
) -> tuple[dict | None, str]:
    """Generate one test function, then construct an append-only EOF patch."""
    if not is_test_path(chosen) or not chosen.endswith(".py"):
        return None, "append_only_test_target_invalid"
    system = """Write exactly ONE pytest test function for the requested boundary condition.
Return Python source only: no JSON, markdown fences, or explanation.
If existing coverage already makes a new test unnecessary, return exactly NO_CHANGE.
Use only imports and fixtures already visible in the current test file.
Do not add imports, decorators, helper functions, classes, or module-level statements.
Do not access the network, environment variables, secrets, files, processes, or the OS.
Do not weaken, edit, rename, reorder, or copy any existing test.
The function name must start with test_. Keep the test focused and concise."""
    if len(context) > MAX_APPEND_ONLY_CONTEXT_CHARS:
        marker = "\n...[middle omitted; append-only context bounded]...\n"
        budget = MAX_APPEND_ONLY_CONTEXT_CHARS - len(marker)
        head_size = budget // 2
        context = context[:head_size] + marker + context[-(budget - head_size):]
    prompt = (
        f"Task:\n{instruction}\n\n"
        f"Only editable file:\n{chosen}\n\n"
        f"Current test file:\n{context}\n\n"
        "Return one complete test function, or NO_CHANGE."
    )
    try:
        generated = ask_text(
            client, system, prompt, max_tokens=MAX_APPEND_ONLY_RESPONSE_TOKENS
        ).strip()
    except Exception as exc:
        detail = _safe_api_error_detail(exc)
        try:
            from importlib.metadata import version as package_version

            sdk_version = package_version("groq")
        except Exception:
            sdk_version = "unknown"
        model = re.sub(r"[^A-Za-z0-9_./-]", "", MODEL)[:100] or "unknown"
        suffix = f":{detail}" if detail else ""
        return None, (
            f"append_only_test_generation_failed:{type(exc).__name__}:"
            f"model={model}:groq_sdk={sdk_version}{suffix}"
        )
    if generated == "NO_CHANGE":
        return {"no_change": True, "source": "append_only_review_task"}, ""
    if not generated or (chr(96) * 3) in generated or len(generated) > 1400:
        return None, "append_only_test_output_invalid"
    try:
        tree = ast.parse(generated, filename=chosen)
    except SyntaxError:
        return None, "append_only_test_invalid_syntax"
    if (
        len(tree.body) != 1
        or not isinstance(tree.body[0], ast.FunctionDef)
        or not tree.body[0].name.startswith("test_")
        or tree.body[0].decorator_list
        or not tree.body[0].body
    ):
        return None, "append_only_test_not_single_function"

    function = tree.body[0]
    forbidden_names = {
        "__builtins__", "__import__", "builtins", "compile", "ctypes",
        "eval", "exec", "globals", "getattr", "getenv", "locals",
        "multiprocessing", "open", "os", "pathlib", "Path", "PurePath",
        "requests", "setattr", "shutil", "socket", "subprocess", "tempfile",
        "threading", "urllib", "vars",
    }
    forbidden_attributes = {
        "Popen", "call", "chdir", "check_call", "check_output", "chmod",
        "connect", "cwd", "environ", "exists", "getenv", "glob", "home",
        "is_dir", "is_file", "iterdir", "mkdir", "open", "read", "read_bytes",
        "read_text", "remove", "rename", "replace", "resolve", "rmdir",
        "rglob", "run", "send", "spawn", "stat", "system", "touch", "unlink",
        "urlopen", "write", "write_bytes", "write_text",
    }
    for node in ast.walk(function):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            return None, "append_only_test_unsafe_operation"
        # Reject references to powerful modules already imported by the test
        # module; generated code must not inherit ambient OS/network capabilities.
        if isinstance(node, ast.Name) and node.id in forbidden_names:
            return None, "append_only_test_unsafe_operation"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in forbidden_names:
                return None, "append_only_test_unsafe_operation"
            if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_attributes:
                return None, "append_only_test_unsafe_operation"
        if isinstance(node, ast.Attribute) and (
            node.attr in forbidden_attributes or node.attr.startswith("__")
        ):
            return None, "append_only_test_unsafe_operation"

    target = ROOT / chosen
    try:
        original = target.read_text(encoding="utf-8")
        original_tree = ast.parse(original, filename=chosen)
    except (OSError, SyntaxError):
        return None, "append_only_test_source_unavailable"
    existing_names = {
        node.name
        for node in ast.walk(original_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }
    if function.name in existing_names:
        return None, "append_only_test_name_exists"

    addition_text = generated.rstrip("\r\n") + "\n"
    original_lines = original.splitlines(keepends=True)
    for start in range(len(original_lines) - 1, -1, -1):
        old = "".join(original_lines[start:])
        if len(old) > 1200:
            break
        if not old.strip() or original.count(old) != 1:
            continue
        new = old.rstrip("\r\n") + "\n\n" + addition_text
        if len(new) > 1800:
            continue
        candidate = original.replace(old, new, 1)
        prefix = original[: -len(old)]
        if not candidate.startswith(prefix) or candidate != prefix + new:
            continue
        try:
            ast.parse(candidate, filename=chosen)
        except SyntaxError:
            continue
        if not _adds_exactly_one_test(chosen, old, new):
            continue
        plan = {
            "no_change": False,
            "source": "append_only_review_task",
            "changes": [{"file": chosen, "old": old, "new": new}],
        }
        valid, detail = validate_plan(plan, chosen)
        if valid and detail != "no_change":
            return plan, ""
    return None, "append_only_test_anchor_or_size_invalid"


def validate_plan_with_bounded_repairs(
    client: Groq,
    instruction: str,
    chosen: str,
    plan: dict,
    context: str,
) -> tuple[dict, bool, str]:
    """Validate a plan and perform only the existing bounded validation repairs."""
    ok, detail = validate_plan(plan, chosen)
    if not ok and detail == "invalid_old_new":
        repair_plan = repair_invalid_old_new_plan(client, instruction, chosen, context, plan, detail)
        ok, detail = validate_plan(repair_plan, chosen)
        if ok:
            plan = repair_plan
    if not ok and detail == "invalid_change_count":
        repair_plan = repair_invalid_change_count_plan(client, instruction, chosen, context, plan)
        ok, detail = validate_plan(repair_plan, chosen)
        if ok and detail != "no_change":
            plan = repair_plan
        else:
            ok, detail = False, "invalid_change_count_repair_failed"
    if not ok and detail == "diff_marker_in_replacement":
        repair_plan = repair_diff_marker_plan(client, instruction, chosen, context, plan)
        ok, detail = validate_plan(repair_plan, chosen)
        if ok:
            plan = repair_plan
    if not ok and detail == "change_too_large":
        repair_plan = repair_size_plan(client, instruction, chosen, context, plan, detail)
        ok, detail = validate_plan(repair_plan, chosen)
        if ok:
            plan = repair_plan
    if not ok and detail == "existing_test_modified":
        repair_plan = repair_existing_test_modified_plan(
            client, instruction, chosen, context, plan
        )
        ok, detail = validate_plan(repair_plan, chosen)
        if (
            ok
            and detail != "no_change"
            and isinstance(repair_plan.get("changes"), list)
            and len(repair_plan["changes"]) == 1
            and _adds_exactly_one_test(
                chosen,
                repair_plan["changes"][0].get("old", ""),
                repair_plan["changes"][0].get("new", ""),
            )
        ):
            plan = repair_plan
        else:
            salvaged_plan = _salvage_additive_test_plan(chosen, repair_plan)
            if salvaged_plan is not None:
                ok, detail = validate_plan(salvaged_plan, chosen)
                if (
                    ok
                    and detail != "no_change"
                    and _adds_exactly_one_test(
                        chosen,
                        salvaged_plan["changes"][0]["old"],
                        salvaged_plan["changes"][0]["new"],
                    )
                ):
                    plan = salvaged_plan
                else:
                    ok, detail = False, "existing_test_modified_repair_failed"
            else:
                ok, detail = False, "existing_test_modified_repair_failed"
    return plan, ok, detail


def apply_plan_with_bounded_anchor_repair(
    client: Groq,
    instruction: str,
    chosen: str,
    plan: dict,
    context: str,
) -> tuple[dict, bool, str, list[str]]:
    """Apply once, then allow exactly one bounded anchor repair on failure."""
    applied, detail, touched = apply_plan(plan)
    if applied:
        return plan, True, detail, touched
    restore(touched)
    if MAX_APPLY_REPAIR_ATTEMPTS < 1:
        return plan, False, detail, touched

    repair_plan = plan
    size_repair_used = False
    for _ in range(MAX_APPLY_REPAIR_ATTEMPTS):
        repair_plan = repair_anchor_plan(
            client,
            instruction,
            chosen,
            context,
            repair_plan,
            detail,
        )
        ok, repair_detail = validate_plan(repair_plan, chosen)
        if not ok and repair_detail == "change_too_large" and not size_repair_used:
            size_repair_used = True
            repair_plan = repair_size_plan(
                client,
                instruction,
                chosen,
                context,
                repair_plan,
                repair_detail,
            )
            ok, repair_detail = validate_plan(repair_plan, chosen)
        if not ok or repair_detail == "no_change":
            return repair_plan, False, repair_detail, []
        target = ROOT / chosen
        old_value = repair_plan["changes"][0]["old"]
        if target.read_text(encoding="utf-8").count(old_value) != 1:
            detail = f"anchor_count_{chosen}:{target.read_text(encoding='utf-8').count(old_value)}"
            continue
        applied, apply_detail, touched = apply_plan(repair_plan)
        if applied:
            return repair_plan, True, apply_detail, touched
        restore(touched)
        detail = apply_detail
    return repair_plan, False, detail, []


def build_comment_test_plan(instruction: str, chosen: str) -> dict | None:
    """Build the legacy self-test edit only when explicitly enabled."""
    if os.environ.get("ALLOW_SELF_TEST_COMMENT") != "1":
        return None
    if chosen != _COMMENT_TEST_PATH or not _COMMENT_REQUEST_PATTERN.search(instruction):
        return None
    if "scripts/line_development.py" not in instruction and "line_development.py" not in instruction:
        return None
    match = re.search(r"[「『\"']([^」』\"']+)[」』\"']", instruction)
    comment_text = (match.group(1) if match else "LINE自動開発テスト").strip()
    comment_text = re.sub(r"[\r\n]+", " ", comment_text)[:120].strip()
    if not comment_text:
        return None
    target = ROOT / _COMMENT_TEST_PATH
    text = target.read_text(encoding="utf-8")
    if f"# {comment_text}" in text:
        return {"no_change": True, "source": "deterministic_self_test"}
    match_anchor = re.search(r"^_WORKFLOW_FILE\s*=\s*\"[^\"\n]+\"\n", text, re.MULTILINE)
    if not match_anchor:
        return None
    anchor = match_anchor.group(0)
    return {"no_change": False, "source": "deterministic_self_test", "changes": [{"file": _COMMENT_TEST_PATH, "old": anchor, "new": anchor + f"# {comment_text}\n"}]}


def _is_allowed_comment_test_change(plan: dict, chosen: str) -> bool:
    """Allow only the narrow deterministic self-test insertion into the protected dispatcher."""
    if chosen != _COMMENT_TEST_PATH or plan.get("no_change") is True:
        return False
    if plan.get("source") != "deterministic_self_test":
        return False
    changes = plan.get("changes")
    if not isinstance(changes, list) or len(changes) != 1:
        return False
    change = changes[0]
    if not isinstance(change, dict) or change.get("file") != _COMMENT_TEST_PATH:
        return False
    old, new = change.get("old"), change.get("new")
    if not isinstance(old, str) or not isinstance(new, str) or not old or not new:
        return False
    if not re.fullmatch(r"_WORKFLOW_FILE\s*=\s*\"[^\"\n]+\"\n", old):
        return False
    suffix = new[len(old):] if new.startswith(old) else ""
    return bool(suffix) and re.fullmatch(r"# [^\r\n]{1,120}\n", suffix) is not None


def _test_definitions_unchanged(path: str, old: str, new: str) -> bool:
    """Reject autonomous edits that alter or remove existing pytest test bodies.

    New test functions may be added, but existing tests must remain byte-for-byte
    equivalent at the AST level so an agent cannot make a failing test pass by
    weakening or rewriting its assertion.
    """
    if not is_test_path(path) or not path.endswith(".py"):
        return True
    target = ROOT / path
    try:
        original = target.read_text(encoding="utf-8")
        # The normal anchor validator handles missing/ambiguous snippets.
        # This guard only runs when the exact replacement target is present once.
        if original.count(old) != 1:
            return True
        candidate = original.replace(old, new, 1)
        before = ast.parse(original, filename=path)
        after = ast.parse(candidate, filename=path)
    except (OSError, SyntaxError, ValueError):
        return False

    def tests(tree):
        found = {}
        def visit(node, scope=()):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = (*scope, child.name)
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test"):
                        found[".".join(name)] = ast.dump(child, include_attributes=False)
                    visit(child, name)
                else:
                    visit(child, scope)
        visit(tree)
        return found

    old_tests, new_tests = tests(before), tests(after)
    return all(new_tests.get(name) == body for name, body in old_tests.items())


def validate_plan(plan: dict, chosen: str) -> tuple[bool, str]:
    if plan.get("no_change") is True:
        return True, "no_change"
    changes = plan.get("changes")
    if not isinstance(changes, list) or len(changes) < 1 or len(changes) > MAX_FILES:
        return False, "invalid_change_count"
    for change in changes:
        if not isinstance(change, dict):
            return False, "invalid_change"
        path, old, new = change.get("file"), change.get("old"), change.get("new")
        if path != chosen:
            return False, "change_outside_selected_file"
        if is_protected(path) and not _is_allowed_comment_test_change(plan, chosen):
            return False, f"protected_file:{path}"
        if (
            not _is_shared_policy_autonomous(path)
            and not _is_allowed_comment_test_change(plan, chosen)
        ):
            return False, f"self_improvement_policy:{_shared_policy_decision(path).value}"
        if not isinstance(old, str) or not old or not isinstance(new, str):
            return False, "invalid_old_new"
        if old == new:
            return False, "no_op_change"
        if is_test_path(path) and not _test_definitions_unchanged(path, old, new):
            return False, "existing_test_modified"
        if any(line.strip() in {"+", "-"} for line in new.splitlines()):
            return False, "diff_marker_in_replacement"
        if len(old) > 1200 or len(new) > 1800:
            return False, "change_too_large"
    return True, chosen


def apply_plan(plan: dict) -> tuple[bool, str, list[str]]:
    """Preflight every bounded change before writing any file."""
    if not isinstance(plan, dict):
        return False, "invalid_plan", []
    if plan.get("no_change") is True:
        return True, "NO_CHANGE", []
    changes = plan.get("changes")
    if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_FILES:
        return False, "invalid_change_count", []

    prepared: list[tuple[str, Path, str, str, str]] = []
    seen_paths: set[str] = set()
    for change in changes:
        if not isinstance(change, dict):
            return False, "invalid_change", []
        path, old, new = change.get("file"), change.get("old"), change.get("new")
        if not isinstance(path, str) or not path or not isinstance(old, str) or not old:
            return False, "invalid_old_new", []
        if not isinstance(new, str) or old == new:
            return False, "invalid_old_new", []
        if path in seen_paths:
            return False, "duplicate_change_path", []
        seen_paths.add(path)
        target = (ROOT / path).resolve()
        try:
            target.relative_to(ROOT.resolve())
        except ValueError:
            return False, "change_path_outside_root", []
        try:
            original = target.read_text(encoding="utf-8")
        except OSError:
            return False, f"change_target_unreadable:{path}", []
        count = original.count(old)
        if count != 1:
            return False, f"anchor_count_{path}:{count}", []
        prepared.append((path, target, original, old, new))

    touched: list[str] = []
    current_index = -1
    try:
        for current_index, (path, target, original, old, new) in enumerate(prepared):
            target.write_text(original.replace(old, new, 1), encoding="utf-8")
            touched.append(path)
    except OSError as exc:
        rollback_errors: list[str] = []
        # Include the failing target: write_text may truncate/write partially
        # before raising, even though it was not appended to touched.
        rollback_targets = prepared[: current_index + 1]
        for path, target, original, _, _ in reversed(rollback_targets):
            try:
                target.write_text(original, encoding="utf-8")
            except OSError:
                rollback_errors.append(path)
        detail = f"apply_write_failed:{type(exc).__name__}"
        if rollback_errors:
            detail += f":rollback_failed={','.join(rollback_errors)}"
        return False, detail, touched
    return True, "applied", touched


def run_tests(touched: list[str] | None = None, *, full_suite: bool = True) -> tuple[bool, str]:
    outputs: list[str] = []
    for path in touched or []:
        if not path.endswith(".py"):
            continue
        compile_result = run([sys.executable, "-m", "py_compile", path], timeout=120)
        outputs.append(f"py_compile {path}: returncode={compile_result.returncode}")
        if compile_result.stdout:
            outputs.append(compile_result.stdout)
        if compile_result.stderr:
            outputs.append(compile_result.stderr)
        if compile_result.returncode != 0:
            return False, "\n".join(outputs)[-8000:]
    # Runtime task context constrains the worker, not the independent full test
    # suite. Tests must not inherit the current task identity/prompt/allowlist:
    # repo_files() may be tested against temporary fixtures, and test subprocesses
    # should never inherit the task's prompt or summary path. Restore all values
    # in the parent process even when pytest raises or times out.
    task_scoped_names = (
        "AUTONOMOUS_ALLOWED_PATHS",
        "AUTONOMOUS_TASK_ID",
        "AUTONOMOUS_SUMMARY_PATH",
        "AUTONOMOUS_RUN_NONCE",
        "AUTONOMOUS_RUN_SOURCE",
        "DEV_INSTRUCTION",
    )
    missing = object()
    task_scope = {name: os.environ.pop(name, missing) for name in task_scoped_names}
    try:
        if full_suite:
            test_cmd = [sys.executable, "-m", "pytest", "-q", "--tb=native"]
            outputs.append("full pytest:")
        else:
            paths = list(touched or [])
            if not paths or any(
                not isinstance(path, str)
                or not path.endswith(".py")
                or Path(path).is_absolute()
                or ".." in Path(path).parts
                for path in paths
            ):
                return False, "targeted pytest requires safe relative Python test paths"
            test_cmd = [sys.executable, "-m", "pytest", "-q", "--tb=native", *paths]
            outputs.append("targeted pytest:")
        tests = run(test_cmd, timeout=900)
    finally:
        for name, value in task_scope.items():
            if value is missing:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    outputs.extend([tests.stdout, tests.stderr])
    return tests.returncode == 0, "\n".join(outputs)[-8000:]


def has_python_compile_failure(output: str) -> bool:
    """Return True when a touched Python file failed its pre-pytest compile check."""
    for line in str(output or "").splitlines():
        match = re.match(r"^py_compile .+: returncode=(-?\d+)$", line.strip())
        if match and int(match.group(1)) != 0:
            return True
    return False


def restore(paths: list[str]) -> None:
    if paths:
        run(["git", "checkout", "--", *paths])


def build_plan(client: Groq, instruction: str, chosen: str, context: str, test_output: str | None = None) -> dict:
    system = (
        "You edit EXACTLY ONE repository file. Return JSON only.\n\n"
        f"The ONLY editable file is: {chosen}\n\n"
        'Real change: {"no_change":false,"changes":[{"file":"exact path","old":"exact existing text","new":"replacement text"}]}\n'
        'No safe/needed change: {"no_change":true}\n\n'
        "Rules:\n"
        f'- changes must contain at most one item, and changes[0]["file"] must be exactly "{chosen}".\n'
        "- Never return another file path.\n"
        '- If the requested improvement requires another file, return {"no_change":true}.\n'
        "- old must be an exact substring of supplied context.\n"
        "- minimal change.\n"
        "- never modify security, credentials, deployment, workflow, or worker logic.\n"
        "- do not invent text that is not visible in context.\n"
        "- The new field is replacement text only: never include unified-diff markers, markdown fences, or standalone +/- lines.\n"
        '- If you cannot express the change safely as exact search/replace, return {"no_change":true}.'
    )
    prompt = (
        f"Instruction:\n{instruction}\n\n"
        f"Selected file (ONLY editable file):\n{chosen}\n\n"
        f"Current context:\n{context}"
    )
    if test_output:
        prompt += f"\n\nPytest failure:\n{test_output[-3000:]}"
    return parse_plan(ask(client, system, prompt, max_tokens=MAX_RESPONSE_TOKENS))


def repair_invalid_old_new_plan(client: Groq, instruction: str, chosen: str, context: str, rejected_plan: dict, validation_error: str = "") -> dict:
    """Perform one bounded repair when the model omitted or malformed old/new fields."""
    rejected = json.dumps(rejected_plan, ensure_ascii=False)
    system = '''Repair ONE rejected JSON search/replace plan. Return JSON only.
Keep the same file and requested intent. Re-read the supplied current file context.
The change MUST contain exactly one object with file, old, and new fields.
The old value MUST be an exact non-empty substring of the current context and the new value
must be replacement text only. Make the smallest possible edit. Never include unified-diff
markers, markdown fences, or standalone +/- lines. Do not invent missing source text or broaden
the requested change. If a safe exact replacement cannot be identified, return {"no_change":true}.'''
    prompt = (
        f"Instruction:\n{instruction}\n\nSelected file:\n{chosen}"
        f"\n\nCurrent file context:\n{context}"
        f"\n\nValidation error:\n{validation_error}"
        f"\n\nRejected plan:\n{rejected}"
    )
    return parse_plan(ask(client, system, prompt, max_tokens=MAX_RESPONSE_TOKENS))



def repair_invalid_change_count_plan(
    client: Groq,
    instruction: str,
    chosen: str,
    context: str,
    rejected_plan: dict,
) -> dict:
    """Regenerate one malformed plan once, without relaxing any validator."""
    rejected = json.dumps(rejected_plan, ensure_ascii=False)
    system = '''Regenerate ONE malformed JSON search/replace plan. Return JSON only.
Return either {"no_change":true} or a plan with exactly one changes object containing file, old, and new.
The file must equal the selected file. The old value must be a non-empty exact substring of current
context; new must be replacement text only. Preserve the original request and do not broaden scope.
Do not invent source text, modify another file, use diff markers, or bypass any safety rule.
If no safe single change can be produced, return {"no_change":true}.'''
    prompt = (
        f"Instruction:\n{instruction}\n\nSelected file (only editable file):\n{chosen}"
        f"\n\nCurrent file context:\n{context}"
        f"\n\nRejected validation reason: invalid_change_count"
        f"\n\nRejected plan:\n{rejected}"
    )
    return parse_plan(ask(client, system, prompt, max_tokens=MAX_RESPONSE_TOKENS))



def repair_diff_marker_plan(client: Groq, instruction: str, chosen: str, context: str, rejected_plan: dict) -> dict:
    """Perform one bounded plan repair focused only on diff-marker contamination."""
    rejected = json.dumps(rejected_plan, ensure_ascii=False)
    system = '''Repair ONE rejected JSON search/replace plan. Return JSON only.
Keep the same file and intent. Re-read the supplied context.
The new field MUST contain plain replacement text only.
Remove unified-diff syntax, patch hunks, markdown fences, and diff-only +/- marker lines.
Do not invent missing source text. Do not broaden the requested change.
If the original plan cannot be converted safely, return {"no_change":true}.'''
    prompt = (
        f"Instruction:\n{instruction}\n\nSelected file:\n{chosen}"
        f"\n\nCurrent context:\n{context}\n\nRejected plan:\n{rejected}"
    )
    return parse_plan(ask(client, system, prompt, max_tokens=MAX_RESPONSE_TOKENS))


def main() -> int:
    instruction = os.environ.get("DEV_INSTRUCTION", "").strip()[:MAX_INSTRUCTION_LENGTH]
    if not instruction:
        print("No development instruction supplied.")
        return 2
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    if is_test_instruction(instruction):
        print("Test-only instruction detected; no file target required.", flush=True)
        passed, output = run_tests()
        print(output, flush=True)
        return 0 if passed else 1

    files = repo_files()
    chosen = choose_file(client, instruction, files)
    if not chosen:
        print("No safe target file selected.")
        return 1
    print("Selected safe target:", chosen, flush=True)
    try:
        try:
            comment_test_plan = build_comment_test_plan(instruction, chosen)
            if comment_test_plan is not None:
                plan = comment_test_plan
            elif is_protected(chosen):
                print("Rejected plan: protected_file_general_edit:" + chosen, flush=True)
                return 1
            else:
                plan = build_plan(client, instruction, chosen, context_for(chosen))
        except (json.JSONDecodeError, ValueError) as exc:
            print("Plan parse failed:", type(exc).__name__, str(exc), flush=True)
            return 1
        except Exception as exc:
            print("Plan generation failed:", type(exc).__name__, str(exc), flush=True)
            traceback.print_exc()
            return 1
        ok, detail = validate_plan(plan, chosen)
        if not ok and detail == "invalid_old_new":
            repair_plan = plan
            for _ in range(MAX_PLAN_REPAIR_ATTEMPTS):
                repair_plan = repair_invalid_old_new_plan(
                    client,
                    instruction,
                    chosen,
                    context_for(chosen),
                    repair_plan,
                )
                ok, detail = validate_plan(repair_plan, chosen)
                if ok:
                    plan = repair_plan
                    break
            else:
                print(
                    "Rejected plan after bounded invalid_old_new repairs:",
                    detail,
                    flush=True,
                )
        if not ok and detail == "invalid_change_count":
            repair_plan = repair_invalid_change_count_plan(
                client, instruction, chosen, context_for(chosen), plan
            )
            ok, detail = validate_plan(repair_plan, chosen)
            if ok and detail != "no_change":
                plan = repair_plan
            else:
                ok, detail = False, "invalid_change_count_repair_failed"
        if not ok and detail == "diff_marker_in_replacement":
            repair_plan = repair_diff_marker_plan(
                client,
                instruction,
                chosen,
                context_for(chosen),
                plan,
            )
            ok, detail = validate_plan(repair_plan, chosen)
            if ok:
                plan = repair_plan
        if not ok and detail == "change_too_large":
            repair_plan = repair_size_plan(
                client,
                instruction,
                chosen,
                context_for(chosen),
                plan,
                detail,
            )
            ok, detail = validate_plan(repair_plan, chosen)
            if ok:
                plan = repair_plan
        if not ok:
            print("Rejected plan:", detail, flush=True)
            return 1
        if detail == "no_change":
            passed, output = run_tests()
            print(output, flush=True)
            return 0 if passed else 1
        plan, applied, detail, touched = apply_plan_with_bounded_anchor_repair(
            client, instruction, chosen, plan, context_for(chosen)
        )
        if not applied:
            print("Apply failed:", detail, flush=True)
            return 1
        passed, output = run_tests(touched)
        print(output, flush=True)
        if not passed and has_python_compile_failure(output):
            restore(touched)
            print("Fail-closed: Python syntax/compile check failed; skipping AI repair call.", flush=True)
            return 1
        attempts = 0
        while not passed and attempts < MAX_REPAIR_ATTEMPTS:
            attempts += 1
            restore(touched)
            if is_protected(chosen):
                repair_plan = build_comment_test_plan(instruction, chosen)
                if repair_plan is None:
                    print("Rejected repair: protected_file_general_edit:" + chosen, flush=True)
                    break
            else:
                repair_plan = build_plan(client, instruction, chosen, context_for(chosen), output)
            ok, detail = validate_plan(repair_plan, chosen)
            if not ok or detail == "no_change":
                break
            applied, detail, touched = apply_plan(repair_plan)
            if not applied:
                restore(touched)
                break
            passed, output = run_tests(touched)
            print(output, flush=True)
        if not passed:
            restore(touched)
            print("Guarded tests failed after repair attempts.", flush=True)
            return 1

        branch = f"line-dev/{os.environ.get('GITHUB_RUN_ID', 'manual')}"
        run(["git", "config", "user.name", "github-actions[bot]"])
        run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
        add = run(["git", "add", "--", *touched])
        if add.returncode != 0:
            restore(touched)
            print(add.stderr[-2000:], flush=True)
            return 1
        status = run(["git", "status", "--short"])
        if status.returncode != 0 or not status.stdout.strip():
            restore(touched)
            print("No changes to commit.", flush=True)
            return 1
        commit = run(["git", "commit", "-m", "feat: LINE development request"])
        if commit.returncode != 0:
            restore(touched)
            print(commit.stderr[-2000:], flush=True)
            return 1
        checkout = run(["git", "checkout", "-B", branch])
        if checkout.returncode != 0:
            print(checkout.stderr[-2000:], flush=True)
            return 1
        print(f"Development branch prepared locally: {branch}", flush=True)
        return 0
    except Exception as exc:
        print("Unexpected worker error:", type(exc).__name__, str(exc), flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
