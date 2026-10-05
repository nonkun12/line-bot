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
MAX_RESPONSE_TOKENS = 4096
MAX_INSTRUCTION_LENGTH = 2000
MAX_REPAIR_ATTEMPTS = 1
MAX_APPLY_REPAIR_ATTEMPTS = 1
MAX_PLAN_REPAIR_ATTEMPTS = 1
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


@lru_cache(maxsize=512)
def _shared_policy_decision(path: str) -> SelfImprovementDecision:
    return assess_self_improvement((path,)).decision


def _is_shared_policy_autonomous(path: str) -> bool:
    return _shared_policy_decision(path) is SelfImprovementDecision.AUTONOMOUS_REVIEW


def repo_files() -> list[str]:
    proc = run(["git", "ls-files"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    return [
        p
        for p in proc.stdout.splitlines()
        if p.endswith(ALLOWED_SUFFIXES)
        and not is_protected(p)
        and _is_shared_policy_autonomous(p)
    ]


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
    if isinstance(chosen, str) and chosen in files and _is_shared_policy_autonomous(chosen):
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


def validate_plan_with_bounded_repairs(
    client: Groq,
    instruction: str,
    chosen: str,
    plan: dict,
    context: str,
) -> tuple[dict, bool, str]:
    """Validate a plan and perform only the existing bounded validation repairs."""
    ok, detail = validate_plan(plan, chosen)
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

    repair_plan = repair_anchor_plan(
        client,
        instruction,
        chosen,
        context,
        plan,
        detail,
    )
    ok, repair_detail = validate_plan(repair_plan, chosen)
    if not ok or repair_detail == "no_change":
        return repair_plan, False, repair_detail, []
    applied, apply_detail, touched = apply_plan(repair_plan)
    if applied:
        return repair_plan, True, apply_detail, touched
    restore(touched)
    return repair_plan, False, apply_detail, touched


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
        if any(line.strip() in {"+", "-"} for line in new.splitlines()):
            return False, "diff_marker_in_replacement"
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


def repair_invalid_old_new_plan(client: Groq, instruction: str, chosen: str, context: str, rejected_plan: dict) -> dict:
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
            repair_plan = repair_invalid_old_new_plan(
                client,
                instruction,
                chosen,
                context_for(chosen),
                plan,
            )
            ok, detail = validate_plan(repair_plan, chosen)
            if ok:
                plan = repair_plan
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
