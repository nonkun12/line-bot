"""Build a new application in its own GitHub repository.

This worker never writes generated source into the AI Secretary repository.
The model proposes files; the worker validates paths, creates the target repo,
checks out its own workspace, runs tests, pushes a branch, and opens a PR.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from urllib import request as urlrequest
from urllib.error import HTTPError

from groq import Groq

MODEL = os.environ.get("DEV_AI_MODEL", "openai/gpt-oss-20b")
MAX_FILES = 12
MAX_FILE_CHARS = 12000
MAX_TOTAL_CHARS = 50000
MAX_REPAIR_ATTEMPTS = 2
MAX_REQUIREMENT_LENGTH = 3000
ALLOWED_SUFFIXES = {".py", ".md", ".html", ".css", ".js", ".json", ".txt"}
FORBIDDEN_NAMES = {".env", ".env.local", ".env.production", "Dockerfile", "render.yaml"}


def run(cmd: list[str], cwd: Path, *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)


def github_api(path: str, token: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urlrequest.Request(
        f"https://api.github.com{path}",
        data=body,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urlrequest.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API HTTP {exc.code}: {raw[:1000]}") from exc


def parse_json(text: str) -> dict:
    clean = str(text or "").strip()
    if not clean:
        raise ValueError("AI response is empty")
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(clean)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    for index, char in enumerate(clean):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(clean[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("AI response does not contain a JSON object")


def slugify(value: str) -> str:
    text = str(value or "").lower()
    replacements = {
        "todo": "ai-todo-app",
        "to-do": "ai-todo-app",
        "タスク": "ai-task-app",
        "家計簿": "ai-household-app",
        "顧客": "ai-customer-app",
    }
    for needle, replacement in replacements.items():
        if needle in text:
            return replacement
    slug = re.sub(r"[^a-z0-9-]+", "-", text).strip("-")
    return slug[:45] or "ai-generated-app"


def normalize_repo_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-.")
    if not name:
        return "ai-generated-app"
    return name[:70]


def safe_relative_path(path: object) -> bool:
    if not isinstance(path, str) or not path.strip():
        return False
    normalized = path.replace("\\", "/").strip()
    if normalized.startswith("/"):
        return False
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        return False
    if any(part.startswith(".") for part in pure.parts):
        return False
    if normalized in FORBIDDEN_NAMES or pure.name in FORBIDDEN_NAMES:
        return False
    return pure.suffix.lower() in ALLOWED_SUFFIXES


def validate_files(files: object) -> tuple[bool, str, list[dict[str, str]]]:
    if not isinstance(files, list) or not files:
        return False, "files must be a non-empty list", []
    if len(files) > MAX_FILES:
        return False, f"file count exceeds {MAX_FILES}", []
    total = 0
    seen: set[str] = set()
    cleaned: list[dict[str, str]] = []
    for item in files:
        if not isinstance(item, dict):
            return False, "file entry must be an object", []
        path = item.get("path")
        content = item.get("content")
        if not safe_relative_path(path):
            return False, f"unsafe path: {path}", []
        normalized = str(path).replace("\\", "/").strip()
        if normalized in seen:
            return False, f"duplicate path: {normalized}", []
        if not isinstance(content, str) or not content:
            return False, f"empty content: {normalized}", []
        if len(content) > MAX_FILE_CHARS:
            return False, f"file too large: {normalized}", []
        seen.add(normalized)
        total += len(content)
        cleaned.append({"path": normalized, "content": content})
    if total > MAX_TOTAL_CHARS:
        return False, f"total generated size exceeds {MAX_TOTAL_CHARS}", []
    return True, "ok", cleaned


def ask(client: Groq, requirement: str, repair: str = "") -> dict:
    system = (
        "You generate a small production-quality Python web application. Return JSON only. "
        "Schema: {\"project_slug\":\"safe-repository-name\",\"summary\":\"short summary\","
        "\"files\":[{\"path\":\"relative/file.py\",\"content\":\"full file content\"}]}. "
        "Use standard-library or minimal Python dependencies. Include pytest tests and a README. "
        "Never emit secrets, credentials, CI workflows, deployment config, shell scripts, subprocess, or os.system. "
        "All paths must be relative and use only .py, .md, .html, .css, .js, .json, or .txt."
    )
    user = f"Requirement:\n{requirement}\n"
    if repair:
        user += f"\nFix the previous test failure. Return the COMPLETE corrected file set:\n{repair[-8000:]}\n"
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=16000,
    )
    return parse_json(response.choices[0].message.content or "")


def create_repository(token: str, owner: str, name: str, description: str) -> str:
    # Reuse an existing repository so repeated LINE requests and workflow
    # retries are idempotent instead of failing on GitHub's duplicate-name 422.
    try:
        existing = github_api(f"/repos/{owner}/{name}", token)
    except RuntimeError as exc:
        if "GitHub API HTTP 404:" not in str(exc):
            raise
        existing = None
    if existing:
        returned_owner = existing.get("owner", {}).get("login", owner)
        return f"{returned_owner}/{existing['name']}"

    try:
        result = github_api(
            "/user/repos",
            token,
            method="POST",
            payload={
                "name": name,
                "description": description[:250],
                "private": True,
                "has_issues": True,
                "has_projects": False,
                "has_wiki": False,
                "auto_init": False,
            },
        )
    except RuntimeError as exc:
        # A concurrent run may create the same repository between the GET and
        # POST. Re-read once and reuse it instead of producing a false failure.
        message = str(exc)
        if "GitHub API HTTP 422:" not in message or "already exists on this account" not in message:
            raise
        existing = github_api(f"/repos/{owner}/{name}", token)
        returned_owner = existing.get("owner", {}).get("login", owner)
        return f"{returned_owner}/{existing['name']}"

    returned_owner = result.get("owner", {}).get("login", owner)
    return f"{returned_owner}/{result['name']}"


def clone_repo(repo: str, token: str, workspace: Path, workdir: Path) -> None:
    result = run(
        ["git", "clone", f"https://x-access-token:{token}@github.com/{repo}.git", str(workspace)],
        workdir,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr[-2000:]}")


def write_files(workspace: Path, files: list[dict[str, str]], *, replace_existing: bool = False) -> list[str]:
    written: list[str] = []
    for item in files:
        target = workspace / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not replace_existing:
            raise RuntimeError(f"refusing to overwrite repository file: {item['path']}")
        target.write_text(item["content"], encoding="utf-8")
        written.append(item["path"])
    return written


def clear_generated_files(workspace: Path, paths: set[str]) -> None:
    for path in sorted(paths, reverse=True):
        target = workspace / path
        if target.is_file():
            target.unlink()


def run_tests(workspace: Path) -> tuple[bool, str]:
    compile_result = run(["python", "-m", "compileall", "-q", "."], workspace, timeout=180)
    if compile_result.returncode != 0:
        return False, compile_result.stderr[-8000:]
    result = run(["python", "-m", "pytest", "-q"], workspace, timeout=900)
    return result.returncode == 0, (result.stdout + "\n" + result.stderr)[-12000:]


def create_pull_request(repo: str, token: str, branch: str, requirement: str, summary: str) -> str:
    payload = {
        "title": "feat: AI generated application",
        "head": branch,
        "base": "main",
        "body": (
            "## AI generated application\n\n"
            f"Requirement:\n{requirement}\n\n"
            f"Summary:\n{summary}\n\n"
            "Generated in an independent repository by the governed AI App Builder.\n"
            "Tests: PASS."
        ),
    }
    result = github_api(f"/repos/{repo}/pulls", token, method="POST", payload=payload)
    return str(result.get("html_url", ""))


def main() -> int:
    requirement = os.environ.get("APP_REQUIREMENT", "").strip()[:MAX_REQUIREMENT_LENGTH]
    token = os.environ.get("APP_GITHUB_TOKEN", "").strip()
    owner = os.environ.get("APP_GITHUB_OWNER", "nonkun12").strip() or "nonkun12"
    if not requirement:
        print("No app requirement supplied")
        return 2
    if not token:
        print("APP_GITHUB_TOKEN is not configured; refusing to create a repository")
        return 2
    try:
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        current_plan = ask(client, requirement)
    except Exception as exc:
        print(f"AI planning failed: {type(exc).__name__}: {exc}")
        return 1

    # For known product families, prefer the deterministic repository name over
    # model-proposed names so retries create the same intended project.
    fallback_slug = slugify(requirement)
    model_slug = normalize_repo_name(current_plan.get("project_slug") or "")
    requested_slug = fallback_slug if fallback_slug != "ai-generated-app" else (model_slug or fallback_slug)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,69}", requested_slug):
        print("Unsafe project slug returned by model")
        return 1
    description = str(current_plan.get("summary") or requirement)[:250]
    try:
        repo = create_repository(token, owner, requested_slug, description)
    except Exception as exc:
        print(f"Repository creation failed: {type(exc).__name__}: {exc}")
        return 1

    generated_paths: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="ai-app-") as temp_dir:
        workspace = Path(temp_dir) / "repo"
        try:
            clone_repo(repo, token, workspace, Path(temp_dir))
            last_failure = ""
            for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
                if attempt:
                    try:
                        current_plan = ask(client, requirement, last_failure)
                    except Exception as exc:
                        print(f"AI repair planning failed: {type(exc).__name__}: {exc}")
                        return 1
                valid, detail, files = validate_files(current_plan.get("files"))
                if not valid:
                    print(f"Rejected model plan: {detail}")
                    return 1
                clear_generated_files(workspace, generated_paths)
                try:
                    written = write_files(workspace, files, replace_existing=False)
                except Exception as exc:
                    print(f"Write failed: {type(exc).__name__}: {exc}")
                    return 1
                generated_paths = set(written)
                passed, output = run_tests(workspace)
                print(output, flush=True)
                if passed:
                    summary = str(current_plan.get("summary") or description)[:2000]
                    branch = f"ai-dev/{os.environ.get('GITHUB_RUN_ID', 'manual')}-{requested_slug}"
                    for key, value in {
                        "user.name": "github-actions[bot]",
                        "user.email": "41898282+github-actions[bot]@users.noreply.github.com",
                    }.items():
                        configured = run(["git", "config", key, value], workspace, timeout=60)
                        if configured.returncode != 0:
                            print(configured.stderr[-4000:])
                            return 1
                    add = run(["git", "add", "--", *sorted(generated_paths)], workspace, timeout=60)
                    if add.returncode != 0:
                        print(add.stderr[-4000:])
                        return 1
                    commit = run(["git", "commit", "-m", "feat: generate application with AI"], workspace, timeout=60)
                    if commit.returncode != 0:
                        print(commit.stderr[-4000:])
                        return 1
                    checkout = run(["git", "switch", "-c", branch], workspace, timeout=60)
                    if checkout.returncode != 0:
                        print(checkout.stderr[-4000:])
                        return 1
                    push = run(["git", "push", "--set-upstream", "origin", branch], workspace, timeout=180)
                    if push.returncode != 0:
                        print(push.stderr[-4000:])
                        return 1
                    pr_url = create_pull_request(repo, token, branch, requirement, summary)
                    print(f"Independent repository: https://github.com/{repo}")
                    print(f"Pull request: {pr_url}")
                    print(f"Repair attempts: {attempt}")
                    return 0
                last_failure = output
                if attempt >= MAX_REPAIR_ATTEMPTS:
                    print("App tests failed after bounded repair attempts")
                    return 1
        except Exception as exc:
            print(f"App build failed: {type(exc).__name__}: {exc}")
            return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
