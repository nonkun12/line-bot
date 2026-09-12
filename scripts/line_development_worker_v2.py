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
_TEST_INSTRUCTION_EXACT = {"開発接続テスト", "接続テスト", "動作確認", "疎通確認"}


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
        response_format={"type": "json_object"},
        reasoning_format="hidden",
    )
    return response.choices[0].message.content or ""


def is_test_instruction(instruction: str) -> bool:
    normalized = str(instruction or "").strip()
    return normalized in _TEST_INSTRUCTION_EXACT or bool(_TEST_INSTRUCTION_PATTERN.fullmatch(normalized))


def _extract_explicit_path(instruction: str, files: list[str]) -> str | None:
    allowed = set(files)
    if _COMMENT_REQUEST_PATTERN.search(instruction):
        allowed.add(_COMMENT_TEST_PATH)
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

    # Prefer the complete response when it is already valid JSON.
    try:
        data = json.loads(clean)
    except json.JSONDecodeError as original_error:
        data = None

        # Handle markdown fenced JSON.
        fenced = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            clean,
            re.IGNORECASE | re.DOTALL,
        )
        if fenced:
            try:
                data = json.loads(fenced.group(1))
            except json.JSONDecodeError:
                data = None

        # Handle a JSON object surrounded by explanatory text.
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
    if chosen != _COMMENT_TEST_PATH or not _COMMENT_REQUEST_PATTERN.search(instruction):
        return None
    if "scripts/line_development.py" not in instruction and "line_development.py" not in instruction:
        return None
    match = re.search(r"[「『\"']([^」』\"']+)[」』\"']", instruction)
    comment_text = (match.group(1) if match else "LINE自動開発テスト").strip()
    comment_text = re.sub(r"[\r\n]+", " ", comment_text)
    comment_text = comment_text[:120].strip()
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
        comment_test = chosen == _COMMENT_TEST_PATH
        if is_protected(path) and not comment_test:
            return False, f"protected_file:{path}"
        if comment_test and not _COMMENT_REQUEST_PATTERN.search(os.environ.get("DEV_INSTRUCTION", "")):
            return False, "protected_file:line_development.py"
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


def build_plan(client: Groq, instruction: str, chosen: str, context: str, test_output: str | None = None) -> dict:
    system = '''You edit ONE repository file. Return JSON only.
Real change: {"no_change":false,"changes":[{"file":"exact path","old":"exact existing text","new":"replacement text"}]}
No safe/needed change: {"no_change":true}
Rules: one file only; old must be an exact substring of supplied context; minimal change; never modify security, credentials, deployment, workflow, or worker logic. Do not invent text that is not visible in context.'''
    prompt = f"Instruction:\n{instruction}\n\nSelected file:\n{chosen}\n\nCurrent context:\n{context}"
    if test_output:
        prompt += f"\n\nPytest failure:\n{test_output[-3000:]}"
    return parse_plan(ask(client, system, prompt, max_tokens=MAX_RESPONSE_TOKENS))


def main() -> int:
    instruction = os.environ.get("DEV_INSTRUCTION", "").strip()[:MAX_INSTRUCTION_LENGTH]
    user_id = os.environ.get("DEV_USER_ID", "")
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
            plan = comment_test_plan if comment_test_plan is not None else build_plan(client, instruction, chosen, context_for(chosen))
        except (json.JSONDecodeError, ValueError) as exc:
            print("Plan parse failed:", type(exc).__name__, str(exc), flush=True)
            return 1
        except Exception as exc:
            print("Plan generation failed:", type(exc).__name__, str(exc), flush=True)
            traceback.print_exc()
            return 1
        ok, detail = validate_plan(plan, chosen)
        if not ok:
            print("Rejected plan:", detail, flush=True)
            return 1
        if detail == "no_change":
            passed, output = run_tests()
            print(output, flush=True)
            return 0 if passed else 1
        applied, detail, touched = apply_plan(plan)
        if not applied:
            restore(touched)
            print("Apply failed:", detail, flush=True)
            return 1
        passed, output = run_tests(touched)
        print(output, flush=True)
        attempts = 0
        while not passed and attempts < MAX_REPAIR_ATTEMPTS:
            attempts += 1
            restore(touched)
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
        push = run(["git", "push", "--set-upstream", "origin", branch])
        if push.returncode != 0:
            print(push.stderr[-2000:], flush=True)
            return 1

        print(f"Development branch pushed: {branch}", flush=True)
        return 0
    except Exception as exc:
        print("Unexpected worker error:", type(exc).__name__, str(exc), flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
