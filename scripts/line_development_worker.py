"""Guarded worker for explicit LINE development instructions.

The worker uses Groq to propose a small unified diff, validates it, runs pytest,
and creates a PR instead of pushing arbitrary development changes to main.
At most one repair attempt is allowed after the first test failure.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from groq import Groq

ROOT = Path(__file__).resolve().parents[1]
MAX_FILES = 4
MAX_FILE_CHARS = 7000
MAX_PATCH_CHARS = 16000
MODEL = os.environ.get("DEV_AI_MODEL", "openai/gpt-oss-20b")

# Development automation must not mutate these classes of files from LINE.
FORBIDDEN_PREFIXES = (
    ".github/",
    ".env",
    "config.py",
    "secrets/",
)
ALLOWED_SUFFIXES = (".py", ".md", ".json", ".txt")


def run(cmd: list[str], timeout: int = 900, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        input=input_text,
        capture_output=True,
        timeout=timeout,
    )


def repo_files() -> list[str]:
    proc = run(["git", "ls-files"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    return [
        p for p in proc.stdout.splitlines()
        if p.endswith(ALLOWED_SUFFIXES) and not p.startswith(FORBIDDEN_PREFIXES)
    ]


def ask(client: Groq, system: str, user: str, max_tokens: int = 5000) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def choose_files(client: Groq, instruction: str, files: list[str]) -> list[str]:
    listing = "\n".join(files)
    raw = ask(
        client,
        "You are a senior software engineer. Return ONLY newline-separated repository paths. Choose at most 4 files that are necessary for the requested change. Never choose .github, config.py, .env, secrets, deployment, or credential files.",
        f"Development instruction:\n{instruction}\n\nRepository files:\n{listing}",
        max_tokens=500,
    )
    chosen: list[str] = []
    allowed = set(files)
    for line in raw.splitlines():
        path = line.strip().strip('`')
        if path in allowed and path not in chosen:
            chosen.append(path)
        if len(chosen) >= MAX_FILES:
            break
    return chosen


def load_context(paths: list[str]) -> str:
    chunks = []
    for path in paths:
        text = (ROOT / path).read_text(encoding="utf-8")
        chunks.append(f"===== {path} =====\n{text[:MAX_FILE_CHARS]}")
    return "\n\n".join(chunks)


def extract_diff(text: str) -> str:
    start = text.find("diff --git ")
    if start >= 0:
        text = text[start:]
    if "```" in text:
        parts = text.split("```")
        candidates = [p for p in parts if "diff --git " in p or p.lstrip().startswith("--- ")]
        if candidates:
            text = candidates[-1]
    return text.strip()


def validate_diff(patch: str) -> tuple[bool, str]:
    if not patch or len(patch) > MAX_PATCH_CHARS:
        return False, "empty_or_oversized_patch"
    if "*** Begin Patch" in patch:
        return False, "non_unified_diff_format"
    changed = set()
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            changed.add(path)
    if not changed or len(changed) > MAX_FILES:
        return False, "too_many_or_no_files"
    for path in changed:
        if path.startswith(FORBIDDEN_PREFIXES) or not path.endswith(ALLOWED_SUFFIXES):
            return False, f"forbidden_file:{path}"
    return True, ",".join(sorted(changed))


def apply_and_test(patch: str) -> tuple[bool, str]:
    check = run(["git", "apply", "--check", "-"], input_text=patch)
    if check.returncode != 0:
        return False, "patch_check_failed\n" + check.stderr[-4000:]
    applied = run(["git", "apply", "-"], input_text=patch)
    if applied.returncode != 0:
        return False, "patch_apply_failed\n" + applied.stderr[-4000:]
    tests = run([sys.executable, "-m", "pytest", "-q", "--tb=native"], timeout=900)
    output = (tests.stdout + "\n" + tests.stderr)[-8000:]
    return tests.returncode == 0, output


def main() -> int:
    instruction = os.environ.get("DEV_INSTRUCTION", "").strip()
    user_id = os.environ.get("DEV_USER_ID", "")
    if not instruction:
        print("No development instruction supplied.")
        return 2

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    files = repo_files()
    chosen = choose_files(client, instruction, files)
    if not chosen:
        print("No safe target files selected.")
        return 1

    context = load_context(chosen)
    system = """You are a senior software engineer implementing one narrowly scoped change.
Return ONLY a unified git diff. Do not include markdown fences or explanations.
Rules: modify only the supplied files; do not add dependencies; do not touch credentials,
configuration, deployment workflows, .github, tests may be added only if one supplied test
file is selected; keep the change minimal; preserve existing behavior outside the request."""
    prompt = f"Instruction from LINE user:\n{instruction}\n\nCurrent repository context:\n{context}"
    patch = extract_diff(ask(client, system, prompt))
    ok, detail = validate_diff(patch)
    if not ok:
        print(f"Rejected patch: {detail}")
        return 1

    passed, test_output = apply_and_test(patch)
    attempts = 1
    if not passed:
        # One repair attempt only. No second repair branch exists.
        repair_prompt = f"""Original instruction:\n{instruction}\n\nPrevious patch:\n{patch}\n\nPytest failure:\n{test_output}\n\nCurrent relevant files after the patch:\n{load_context(chosen)}\n\nReturn ONLY a corrected unified diff. Fix only the failure while preserving the requested change."""
        repair_patch = extract_diff(ask(client, system, repair_prompt))
        ok2, detail2 = validate_diff(repair_patch)
        if not ok2:
            print(f"Repair rejected: {detail2}")
            return 1
        # Restore the pre-repair state before applying the replacement patch.
        run(["git", "checkout", "--", *chosen])
        passed, test_output = apply_and_test(repair_patch)
        patch = repair_patch
        attempts = 2

    if not passed:
        run(["git", "checkout", "--", *chosen])
        print(f"Development failed after {attempts} attempt(s).\n{test_output}")
        return 1

    status = run(["git", "status", "--short"])
    if not status.stdout.strip():
        print("Tests passed but no files changed.")
        return 0

    branch = f"line-dev/{os.environ.get('GITHUB_RUN_ID', 'manual')}"
    branch_check = run(["git", "checkout", "-b", branch])
    if branch_check.returncode != 0:
        print(branch_check.stderr[-2000:])
        return 1
    run(["git", "config", "user.name", "line-development-worker"])
    run(["git", "config", "user.email", "line-development-worker@users.noreply.github.com"])
    run(["git", "add", "--", *chosen])
    commit = run(["git", "commit", "-m", f"feat: implement LINE development request"])
    if commit.returncode != 0:
        print(commit.stderr[-2000:])
        return 1
    push = run(["git", "push", "--set-upstream", "origin", branch])
    if push.returncode != 0:
        print(push.stderr[-2000:])
        return 1

    # gh is preinstalled on GitHub-hosted runners. The checkout token provides auth.
    pr_body = (
        "## LINE development request\n\n"
        f"{instruction}\n\n"
        f"User: `{user_id}`\n\n"
        f"Pytest: PASS\nRepair attempts: {attempts}\n\n"
        "This PR was created by the guarded LINE development worker."
    )
    pr = run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", "feat: LINE development request", "--body", pr_body])
    print(f"Development complete.\n{pr.stdout[-4000:]}\n{test_output[-4000:]}")
    return 0 if pr.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
