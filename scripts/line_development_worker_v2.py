"""Guarded LINE development worker v2.

AI proposes structured search/replace operations instead of raw unified diffs.
Python validates the operations, applies guarded tests, and opens a PR.
Security-sensitive files are never editable by this worker.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from groq import Groq

ROOT = Path(__file__).resolve().parents[1]
MODEL = os.environ.get("DEV_AI_MODEL", "openai/gpt-oss-20b")
MAX_FILES = 1
MAX_FILE_CHARS = 4500
MAX_RESPONSE_TOKENS = 1800
MAX_INSTRUCTION_LENGTH = 2000
MAX_REPAIR_ATTEMPTS = 1
ALLOWED_SUFFIXES = (".py", ".md", ".json", ".txt")
PROTECTED_PATHS = {
    ".github", ".env", "config.py",
    "scripts/line_development_worker.py",
    "scripts/line_development_worker_safe.py",
    "scripts/line_development_worker_v2.py",
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


def repo_files() -> list[str]:
    proc = run(["git", "ls-files"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    return [p for p in proc.stdout.splitlines() if p.endswith(ALLOWED_SUFFIXES) and not is_protected(p)]


def ask(client: Groq, system: str, user: str, max_tokens: int = MAX_RESPONSE_TOKENS) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=max_tokens,
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
        if token in allowed:
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

    prompt = f"Instruction:\n{instruction}\n\nEligible files:\n" + "\n".join(files)
    try:
        data = parse_plan(ask(client, "Select exactly one eligible file and return JSON only: {\"file\":\"path\"} or {\"file\":null}", prompt))
    except Exception:
        return None
    chosen = data.get("file")
    if isinstance(chosen, str) and chosen in files:
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
    target = ROOT / path
    return target.read_text(encoding="utf-8")[:MAX_FILE_CHARS]


def build_comment_test_plan(instruction: str, chosen: str) -> dict | None:
    """Build the legacy self-test edit only when explicitly enabled.

    This path is intentionally disabled by default because ``line_development.py``
    is a protected control-plane file. It exists only for a deliberate local/CI
    self-test with ``ALLOW_SELF_TEST_COMMENT=1``.
    """
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
        return {"no_change": True}
    match_anchor = re.search(r"^_WORKFLOW_FILE\s*=\s*\"[^\"\n]+\"\n", text, re.MULTILINE)
    if not match_anchor:
        return None
    anchor = match_anchor.group(0)
    return {"no_change": False, "changes": [{"file": _COMMENT_TEST_PATH, "old": anchor, "new": anchor + f"# {comment_text}\n"}]}


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
        if is_protected(path):
            return False, f"protected_file:{path}"
        if not isinstance(old, str) or not old or not isinstance(new, str):
            return False, "invalid_old_new"
        if old == new:
            return False, "no_op_change"
        if len(old) > 1200 or len(new) > 1800:
            return False, "change_too_large"
    return True, chosen


def apply_plan(plan: dict) -> tuple[bool, str, list[str]]:
    if plan.get("no_change") is True:
        return True, "NO_CHANGE", []
    touched: list[str] = []
    for change in plan["changes"]:
        target = ROOT / change["file"]
        text = target.read_text(encoding="utf-8")
        count = text.count(change["old"])
        if count != 1:
            return False, f"anchor_count_{change['file']}:{count}", touched
        target.write_text(text.replace(change["old"], change["new"], 1), encoding="utf-8")
        touched.append(change["file"])
    return True, "applied", touched


def run_tests(touched: list[str] | None = None) -> tuple[bool, str]:
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
    tests = run([sys.executable, "-m", "pytest", "-q", "--tb=native"], timeout=900)
    outputs.append("full pytest:")
    outputs.extend([tests.stdout, tests.stderr])
    return tests.returncode == 0, "\n".join(outputs)[-8000:]


def restore(paths: list[str]) -> None:
    if paths:
        run(["git", "checkout", "--", *paths])
