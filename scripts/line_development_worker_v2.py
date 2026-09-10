"""Guarded LINE development worker v2.

AI proposes structured search/replace operations instead of raw unified diffs.
Python validates the operations, applies them, runs pytest, and opens a PR.
Security-sensitive files are never editable by this worker.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

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
    "scripts/line_development.py", "line_development.py",
    "git_safety.py", "patch_validator.py", "render_client.py",
}
PROTECTED_PREFIXES = (".github/", "secrets/", ".git/")


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
    )
    return response.choices[0].message.content or ""


def choose_file(client: Groq, instruction: str, files: list[str]) -> str | None:
    system = 'Choose exactly one repository file. Return JSON only: {"file":"path"} or {"file":null}. Never choose security, credential, deployment, workflow, or worker files.'
    listing = "\n".join(files[:250])
    raw = ask(client, system, f"Instruction:\n{instruction}\n\nAllowed files:\n{listing}", max_tokens=250)
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None
    path = data.get("file") if isinstance(data, dict) else None
    return path if isinstance(path, str) and path in files and not is_protected(path) else None


def context_for(path: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    return text[:MAX_FILE_CHARS]


def parse_plan(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("plan must be an object")
    return data


def validate_plan(plan: dict, chosen: str) -> tuple[bool, str]:
    if plan.get("no_change") is True:
        return True, "no_change"
    changes = plan.get("changes")
    if not isinstance(changes, list) or not changes:
        return False, "missing_changes"
    if len(changes) > 4:
        return False, "too_many_changes"
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


def run_tests() -> tuple[bool, str]:
    tests = run([sys.executable, "-m", "pytest", "-q", "--tb=native"], timeout=900)
    return tests.returncode == 0, (tests.stdout + "\n" + tests.stderr)[-8000:]


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
    files = repo_files()
    chosen = choose_file(client, instruction, files)
    if not chosen:
        print("No safe target file selected.")
        return 1
    print("Selected safe target:", chosen)
    try:
        plan = build_plan(client, instruction, chosen, context_for(chosen))
    except (json.JSONDecodeError, ValueError) as exc:
        print("Plan parse failed:", type(exc).__name__)
        return 1
    ok, detail = validate_plan(plan, chosen)
    if not ok:
        print("Rejected plan:", detail)
        return 1
    if detail == "no_change":
        passed, output = run_tests()
        print(output)
        return 0 if passed else 1
    applied, detail, touched = apply_plan(plan)
    if not applied:
        restore(touched)
        print("Plan apply failed:", detail)
        return 1
    passed, output = run_tests()
    attempts = 0
    while not passed and attempts < MAX_REPAIR_ATTEMPTS:
        attempts += 1
        restore(touched)
        try:
            repair = build_plan(client, instruction, chosen, context_for(chosen), output)
        except (json.JSONDecodeError, ValueError) as exc:
            print("Repair plan parse failed:", type(exc).__name__)
            return 1
        ok, detail = validate_plan(repair, chosen)
        if not ok or detail == "no_change":
            print("Repair rejected:", detail)
            return 1
        applied, detail, touched = apply_plan(repair)
        if not applied:
            restore(touched)
            print("Repair apply failed:", detail)
            return 1
        passed, output = run_tests()
    if not passed:
        restore(touched)
        print(f"Development failed after {attempts + 1} attempt(s).\n{output}")
        return 1
    status = run(["git", "status", "--short"])
    if not status.stdout.strip():
        print("Tests passed but no files changed.")
        return 0
    branch = f"line-dev/{os.environ.get('GITHUB_RUN_ID', 'manual')}"
    if run(["git", "checkout", "-b", branch]).returncode != 0:
        return 1
    run(["git", "config", "user.name", "line-development-worker"])
    run(["git", "config", "user.email", "line-development-worker@users.noreply.github.com"])
    run(["git", "add", "--", *touched])
    if run(["git", "commit", "-m", "feat: implement LINE development request"]).returncode != 0:
        return 1
    if run(["git", "push", "--set-upstream", "origin", branch]).returncode != 0:
        return 1
    pr_body = f"## LINE development request\n\n{instruction}\n\nUser: `{user_id}`\n\nPytest: PASS\nRepair attempts: {attempts}\n"
    pr = run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", "feat: LINE development request", "--body", pr_body])
    print(pr.stdout[-4000:])
    return 0 if pr.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
