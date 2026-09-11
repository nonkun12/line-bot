"""Guarded autonomous nightly task worker.

The worker implements exactly one narrowly-scoped development task on main.
It may edit only a small allowlisted set of source/documentation files, runs
pytest, allows at most one repair attempt, and commits only after tests pass.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from groq import Groq

ROOT = Path(__file__).resolve().parents[1]
MAX_FILES = 4
MAX_FILE_CHARS = 9000
MAX_PATCH_CHARS = 18000
MODEL = os.environ.get("DEV_AI_MODEL", "openai/gpt-oss-20b")
FORBIDDEN_PREFIXES = (".github/", ".env", "config.py", "secrets/")
ALLOWED_SUFFIXES = (".py", ".md", ".json", ".txt")


def run(cmd: list[str], *, input_text: str | None = None, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, input=input_text, capture_output=True, timeout=timeout)


def ask(client: Groq, system: str, user: str, max_tokens: int = 4000) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def repo_files() -> list[str]:
    proc = run(["git", "ls-files"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    return [p for p in proc.stdout.splitlines() if p.endswith(ALLOWED_SUFFIXES) and not p.startswith(FORBIDDEN_PREFIXES)]


def choose_files(client: Groq, instruction: str, files: list[str]) -> list[str]:
    raw = ask(
        client,
        "Return ONLY newline-separated repository paths. Choose at most 4 files necessary for the task. Never choose .github, config.py, .env, secrets, deployment or credential files.",
        f"Task:\n{instruction}\n\nFiles:\n{chr(10).join(files)}",
        600,
    )
    allowed = set(files)
    chosen: list[str] = []
    for line in raw.splitlines():
        path = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line.strip().strip('`')).strip()
        if path in allowed and path not in chosen:
            chosen.append(path)
        if len(chosen) >= MAX_FILES:
            break
    return chosen


def context(paths: list[str]) -> str:
    return "\n\n".join(f"===== {p} =====\n{(ROOT / p).read_text(encoding='utf-8')[:MAX_FILE_CHARS]}" for p in paths)


def extract_diff(text: str) -> str:
    start = text.find("diff --git ")
    if start >= 0:
        text = text[start:]
    if "```" in text:
        parts = text.split("```")
        candidates = [p for p in parts if "diff --git " in p]
        if candidates:
            text = candidates[-1]
    return text.strip()


def validate_diff(patch: str) -> tuple[bool, str]:
    if not patch or len(patch) > MAX_PATCH_CHARS or "*** Begin Patch" in patch:
        return False, "empty_oversized_or_wrong_format"
    changed = {line[6:].strip() for line in patch.splitlines() if line.startswith("+++ b/")}
    if not changed or len(changed) > MAX_FILES:
        return False, "too_many_or_no_files"
    for path in changed:
        if path.startswith(FORBIDDEN_PREFIXES) or not path.endswith(ALLOWED_SUFFIXES):
            return False, f"forbidden_file:{path}"
    return True, ",".join(sorted(changed))


def apply_and_test(patch: str) -> tuple[bool, str]:
    check = run(["git", "apply", "--check", "-"], input_text=patch)
    if check.returncode != 0:
        return False, check.stderr[-5000:]
    applied = run(["git", "apply", "-"], input_text=patch)
    if applied.returncode != 0:
        return False, applied.stderr[-5000:]
    tests = run(["python", "-m", "pytest", "-q", "--tb=native"], timeout=900)
    return tests.returncode == 0, (tests.stdout + "\n" + tests.stderr)[-10000:]


def main() -> int:
    instruction = os.environ.get("DEV_INSTRUCTION", "").strip()
    if not instruction:
        return 2
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    files = repo_files()
    chosen = choose_files(client, instruction, files)
    if not chosen:
        print("No safe target files selected.")
        return 1

    system = """You are a senior software engineer implementing one narrowly scoped improvement to an existing AI assistant control tower.
Return ONLY a unified git diff. Modify only supplied files. Do not add dependencies, touch credentials/config/deployment/.github, or rewrite unrelated logic.
Preserve existing behavior. Add tests when an existing test file is among the supplied files. Keep the change minimal and production-safe."""
    patch = extract_diff(ask(client, system, f"Instruction:\n{instruction}\n\nCurrent files:\n{context(chosen)}", 3000))
    if not patch:
        print("No patch generated.")
        return 1

    ok, detail = validate_diff(patch)
    if not ok:
        print(f"Patch rejected: {detail}")
        return 1

    passed, output = apply_and_test(patch)
    attempts = 1
    if not passed:
        repair_prompt = f"""Fix only the failed implementation while preserving the requested change.
Original task:\n{instruction}\n\nPatch:\n{patch}\n\nPytest failure:\n{output}\n\nCurrent files:\n{context(chosen)}\n\nReturn ONLY a corrected unified diff."""
        repair_patch = extract_diff(ask(client, system, repair_prompt, 3000))
        ok2, detail2 = validate_diff(repair_patch)
        if not ok2:
            print(f"Repair rejected: {detail2}")
            run(["git", "checkout", "--", *chosen])
            return 1
        run(["git", "checkout", "--", *chosen])
        passed, output = apply_and_test(repair_patch)
        patch = repair_patch
        attempts = 2

    if not passed:
        run(["git", "checkout", "--", *chosen])
        print(f"Task failed after {attempts} attempt(s).\n{output}")
        return 1

    status = run(["git", "status", "--short"])
    if not status.stdout.strip():
        print("Tests passed but no files changed.")
        return 0

    run(["git", "config", "user.name", "nightly-autonomous-worker"])
    run(["git", "config", "user.email", "nightly-worker@users.noreply.github.com"])
    add = run(["git", "add", "--", *chosen])
    if add.returncode != 0:
        print(add.stderr[-2000:])
        return 1
    commit = run(["git", "commit", "-m", "feat: improve AI control tower"])
    if commit.returncode != 0:
        print(commit.stderr[-2000:])
        return 1
    print(f"Nightly control-tower task completed. files={detail} repair_attempts={attempts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
