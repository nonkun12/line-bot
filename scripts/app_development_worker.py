"""Guarded autonomous app-development worker.

The AI may generate application source files only below apps/<slug>/. The worker,
not the model, controls filesystem safety, test execution, git push, and PR creation.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from urllib import error as urllib_error
from urllib import request as urllib_request

from groq import Groq

ROOT = Path(__file__).resolve().parents[1]
MODEL = os.environ.get("DEV_AI_MODEL", "openai/gpt-oss-20b")
MAX_FILES = 6
MAX_TOTAL_CHARS = 30000
MAX_FILE_CHARS = 10000
MAX_REQUIREMENT_LENGTH = 3000
MAX_REPAIR_ATTEMPTS = 2
PROTECTED_PREFIXES = (".github/", ".git/", "secrets/")
PROTECTED_NAMES = {
    ".env", ".env.local", ".env.production", "config.py", "render.yaml", "Dockerfile",
    "scripts/app_development_worker.py", "scripts/line_development_worker_v2.py",
    "scripts/line_development_worker.py", "scripts/line_development_worker_safe.py",
    "git_safety.py", "patch_validator.py",
}


def run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)


def ask(client: Groq, system: str, user: str, max_tokens: int = 12000) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def parse_json(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.strip("`").strip()
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()
    data = json.loads(clean)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.lower()).strip("-")
    return value[:40] or "generated-app"


def safe_path(path: str, slug: str) -> bool:
    if not isinstance(path, str) or not path:
        return False
    normalized = path.replace("\\", "/").lstrip("./")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        return False
    if not normalized.startswith(f"apps/{slug}/"):
        return False
    if normalized in PROTECTED_NAMES or any(normalized.startswith(p) for p in PROTECTED_PREFIXES):
        return False
    return True


def validate_files(files: object, slug: str) -> tuple[bool, str, list[dict]]:
    if not isinstance(files, list) or not files:
        return False, "files must be a non-empty list", []
    if len(files) > MAX_FILES:
        return False, f"file count exceeds {MAX_FILES}", []
    clean: list[dict] = []
    total = 0
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            return False, "file entry must be an object", []
        path = item.get("path")
        content = item.get("content")
        if not safe_path(path, slug):
            return False, f"unsafe path: {path}", []
        if path in seen:
            return False, f"duplicate path: {path}", []
        if not isinstance(content, str) or not content:
            return False, f"empty content: {path}", []
        if len(content) > MAX_FILE_CHARS:
            return False, f"file too large: {path}", []
        target = ROOT / path
        if target.exists() and target.is_file():
            return False, f"existing file overwrite refused: {path}", []
        seen.add(path)
        total += len(content)
        clean.append({"path": path, "content": content})
    if total > MAX_TOTAL_CHARS:
        return False, f"total generated size exceeds {MAX_TOTAL_CHARS} chars", []
    return True, "ok", clean


def build_prompt(requirement: str, slug: str, repair_output: str = "") -> tuple[str, str]:
    system = """You are an application code generator. Return JSON only.
Schema: {\"files\":[{\"path\":\"apps/<slug>/relative/path\",\"content\":\"full UTF-8 file content\"}],\"summary\":\"short summary\"}
Hard rules: generate a small Python web application using only dependencies already present in requirements.txt when possible; paths MUST stay under apps/<slug>/; never generate .env, credentials, CI/workflow, deployment config, or arbitrary shell scripts; do not use subprocess/os.system; include pytest tests; keep the first implementation small and runnable; only create new files, never assume an existing generated-app file should be overwritten.
For repair requests, preserve working behavior and fix only the reported failure while staying within the same app directory.
"""
    user = f"Requirement:\n{requirement}\n\nApp slug: {slug}\n"
    if repair_output:
        user += f"\nPrevious test failure:\n{repair_output[-7000:]}\nRepair the generated app."
    return system, user


def write_files(files: list[dict], slug: str) -> list[str]:
    touched: list[str] = []
    root = ROOT / "apps" / slug
    root.mkdir(parents=True, exist_ok=True)
    for item in files:
        target = ROOT / item["path"]
        if target.exists():
            raise RuntimeError(f"refusing to overwrite existing path: {item['path']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["content"], encoding="utf-8")
        touched.append(item["path"])
    return touched


def cleanup(touched: list[str]) -> None:
    for path in sorted(touched, reverse=True):
        target = ROOT / path
        try:
            target.unlink()
        except FileNotFoundError:
            pass
    for parent in sorted({(ROOT / p).parent for p in touched}, key=lambda x: len(x.parts), reverse=True):
        try:
            parent.rmdir()
        except OSError:
            pass


def run_tests(slug: str) -> tuple[bool, str]:
    outputs: list[str] = []
    base = ROOT / "apps" / slug
    for py in base.rglob("*.py"):
        result = run([sys.executable, "-m", "py_compile", str(py)], timeout=120)
        outputs.append(f"py_compile {py.relative_to(ROOT)}: {result.returncode}\n{result.stdout}\n{result.stderr}")
        if result.returncode != 0:
            return False, "\n".join(outputs)[-9000:]
    tests = run([sys.executable, "-m", "pytest", "-q", str(base)], timeout=900)
    outputs.append(tests.stdout)
    outputs.append(tests.stderr)
    return tests.returncode == 0, "\n".join(outputs)[-12000:]


def create_pr(branch: str, requirement: str, summary: str, attempts: int) -> tuple[bool, str]:
    key = os.environ.get("INTERNAL_PUSH_KEY", "").strip()
    if not key:
        return False, "INTERNAL_PUSH_KEY is not configured"
    payload = json.dumps({
        "head": branch,
        "title": "feat: AI generated application",
        "body": f"## AI generated application\n\nRequirement:\n{requirement}\n\nSummary:\n{summary}\n\nGuarded app tests: PASS\nRepair attempts: {attempts}\n",
        "repository": os.environ.get("GITHUB_REPOSITORY", "nonkun12/line-bot"),
    }).encode("utf-8")
    request = urllib_request.Request(
        "https://line-bot-yvea.onrender.com/internal/create-pr",
        data=payload,
        headers={"Content-Type": "application/json", "x-internal-key": key},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
            data = json.loads(raw or "{}")
            if response.status == 201 and data.get("ok"):
                return True, str(data.get("url") or "PR created")
            return False, f"Render PR relay HTTP {response.status}: {raw[-2000:]}"
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return False, f"Render PR relay HTTP {exc.code}: {raw[-2000:]}"
    except Exception as exc:
        return False, f"Render PR relay failed: {type(exc).__name__}: {exc}"


def main() -> int:
    requirement = os.environ.get("APP_REQUIREMENT", "").strip()[:MAX_REQUIREMENT_LENGTH]
    user_id = os.environ.get("APP_USER_ID", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "manual")
    if not requirement:
        print("No app requirement supplied")
        return 2
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    base_slug = slugify(requirement.split()[0] if requirement else "generated-app")
    slug = f"{base_slug}-{run_id[-8:]}" if run_id != "manual" else base_slug
    branch = f"app-dev/{run_id}-{slug}"
    touched: list[str] = []
    last_output = ""
    summary = ""
    attempts_used = 0

    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        attempts_used = attempt
        system, user = build_prompt(requirement, slug, last_output)
        try:
            plan = parse_json(ask(client, system, user))
        except Exception as exc:
            print(f"AI plan parse failed: {type(exc).__name__}: {exc}")
            cleanup(touched)
            return 1
        valid, detail, files = validate_files(plan.get("files"), slug)
        if not valid:
            print(f"Rejected app plan: {detail}")
            cleanup(touched)
            return 1
        cleanup(touched)
        try:
            touched = write_files(files, slug)
        except Exception as exc:
            print(f"Write failed: {type(exc).__name__}: {exc}")
            cleanup(touched)
            return 1
        summary = str(plan.get("summary") or "AI generated application")[:2000]
        passed, output = run_tests(slug)
        print(output, flush=True)
        if passed:
            break
        last_output = output
        if attempt >= MAX_REPAIR_ATTEMPTS:
            cleanup(touched)
            print("App tests failed after repair attempts.")
            return 1
    else:
        cleanup(touched)
        return 1

    config = run(["git", "config", "user.name", "github-actions[bot]"])
    config2 = run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    if config.returncode != 0 or config2.returncode != 0:
        cleanup(touched)
        return 1
    add = run(["git", "add", "--", *touched])
    if add.returncode != 0:
        cleanup(touched)
        return 1
    status = run(["git", "status", "--short"])
    if status.returncode != 0 or not status.stdout.strip():
        cleanup(touched)
        return 1
    commit = run(["git", "commit", "-m", "feat: generate application with AI"])
    if commit.returncode != 0:
        cleanup(touched)
        return 1
    checkout = run(["git", "checkout", "-B", branch])
    if checkout.returncode != 0:
        return 1
    push = run(["git", "push", "--set-upstream", "origin", branch])
    if push.returncode != 0:
        print(push.stderr[-4000:])
        return 1
    created, detail = create_pr(branch, requirement, summary, attempts_used)
    if not created:
        print(detail)
        return 1
    print(f"PR: {detail}")
    print(f"APP_PROJECT_PATH=apps/{slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
