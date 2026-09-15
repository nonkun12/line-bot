"""Entry point for AI app generation with an empty-repository base branch."""
from __future__ import annotations

import ast
import os
import re
import tempfile
from pathlib import Path

from groq import Groq

from universal_app_builder import (
    MAX_REPAIR_ATTEMPTS,
    MAX_REQUIREMENT_LENGTH,
    clear_generated_files,
    clone_repo,
    create_pull_request,
    create_repository,
    normalize_repo_name,
    ask as generate_plan,
    run,
    run_tests,
    slugify,
    validate_files,
    write_files,
)


def ask(client: Groq, requirement: str, repair: str = "") -> dict:
    """Request a structured application plan with JSON-only model output."""
    system = (
        "You generate a small production-quality Python web application. Return JSON only. "
        "Schema: {\"project_slug\":\"safe-repository-name\",\"summary\":\"short summary\","
        "\"files\":[{\"path\":\"relative/file.py\",\"content\":\"full file content\"}]}. "
        "Use standard-library or minimal Python dependencies. Include pytest tests and a README. "
        "Never emit secrets, credentials, CI workflows, deployment config, shell scripts, subprocess, or os.system. "
        "All paths must be relative and use only .py, .md, .html, .css, .js, .json, or .txt. "
        "Target Flask 3.x when Flask is used: never use before_first_request."
    )
    user = f"Requirement:\n{requirement}\n"
    if repair:
        user += f"\nFix the previous test failure. Return the COMPLETE corrected file set:\n{repair[-8000:]}\n"
    response = client.chat.completions.create(
        model=os.environ.get("DEV_AI_MODEL", "openai/gpt-oss-20b"),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=16000,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise ValueError("AI response is empty")
    try:
        value = __import__("json").loads(content)
    except __import__("json").JSONDecodeError as exc:
        raise ValueError(f"AI response is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("AI response is not a JSON object")
    return value


def ensure_main_base(workspace: Path) -> None:
    """Guarantee that the target repository has a PR base branch named main."""
    has_head = run(["git", "rev-parse", "--verify", "HEAD"], workspace, timeout=60)
    if has_head.returncode == 0:
        main_ref = run(["git", "show-ref", "--verify", "refs/remotes/origin/main"], workspace, timeout=60)
        if main_ref.returncode != 0:
            switch = run(["git", "switch", "-C", "main"], workspace, timeout=60)
            if switch.returncode != 0:
                raise RuntimeError(f"cannot establish main branch: {switch.stderr[-2000:]}")
            push = run(["git", "push", "--set-upstream", "origin", "main"], workspace, timeout=180)
            if push.returncode != 0:
                raise RuntimeError(f"cannot push main branch: {push.stderr[-2000:]}")
        return

    switch = run(["git", "switch", "-c", "main"], workspace, timeout=60)
    if switch.returncode != 0:
        raise RuntimeError(f"cannot initialize main branch: {switch.stderr[-2000:]}")
    config_name = run(["git", "config", "user.name", "github-actions[bot]"], workspace, timeout=60)
    config_email = run(
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        workspace,
        timeout=60,
    )
    if config_name.returncode != 0 or config_email.returncode != 0:
        raise RuntimeError("cannot configure git identity")
    empty_commit = run(["git", "commit", "--allow-empty", "-m", "chore: initialize application repository"], workspace, timeout=60)
    if empty_commit.returncode != 0:
        raise RuntimeError(f"cannot create main base commit: {empty_commit.stderr[-2000:]}")
    push = run(["git", "push", "--set-upstream", "origin", "main"], workspace, timeout=180)
    if push.returncode != 0:
        raise RuntimeError(f"cannot push main base branch: {push.stderr[-2000:]}")


def repair_known_flask3_issues(workspace: Path, generated_paths: set[str], test_output: str) -> bool:
    """Apply deterministic, AST-safe fixes for known Flask 3 incompatibilities."""
    if "before_first_request" not in test_output:
        return False
    changed = False
    for relative_path in sorted(generated_paths):
        if not relative_path.endswith(".py"):
            continue
        target = workspace / relative_path
        if not target.is_file():
            continue
        source = target.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=relative_path)
        except SyntaxError:
            continue
        callbacks: list[str] = []
        file_changed = False
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            kept: list[ast.expr] = []
            removed = False
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Attribute)
                    and decorator.attr == "before_first_request"
                    and isinstance(decorator.value, ast.Name)
                    and decorator.value.id == "app"
                ):
                    removed = True
                    continue
                kept.append(decorator)
            if removed:
                node.decorator_list = kept
                callbacks.append(node.name)
                file_changed = True
        if not file_changed:
            continue
        for callback_name in callbacks:
            call = ast.Expr(value=ast.Call(func=ast.Name(id=callback_name, ctx=ast.Load()), args=[], keywords=[]))
            context = ast.With(
                items=[
                    ast.withitem(
                        context_expr=ast.Call(
                            func=ast.Attribute(value=ast.Name(id="app", ctx=ast.Load()), attr="app_context", ctx=ast.Load()),
                            args=[],
                            keywords=[],
                        ),
                        optional_vars=None,
                    )
                ],
                body=[call],
            )
            tree.body.append(context)
        ast.fix_missing_locations(tree)
        target.write_text(ast.unparse(tree) + "\n", encoding="utf-8")
        changed = True
        print(f"Applied deterministic Flask 3 compatibility repair: {relative_path}", flush=True)
    return changed


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
            ensure_main_base(workspace)
            branch = f"ai-dev/{os.environ.get('GITHUB_RUN_ID', 'manual')}-{requested_slug}"
            checkout = run(["git", "switch", "-c", branch, "origin/main"], workspace, timeout=60)
            if checkout.returncode != 0:
                raise RuntimeError(f"cannot create development branch: {checkout.stderr[-2000:]}")

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
                written = write_files(workspace, files, replace_existing=True)
                generated_paths = set(written)
                passed, output = run_tests(workspace)
                print(output, flush=True)
                if not passed and repair_known_flask3_issues(workspace, generated_paths, output):
                    passed, output = run_tests(workspace)
                    print(output, flush=True)
                if passed:
                    summary = str(current_plan.get("summary") or description)[:2000]
                    add = run(["git", "add", "--", *sorted(generated_paths)], workspace, timeout=60)
                    if add.returncode != 0:
                        raise RuntimeError(f"git add failed: {add.stderr[-2000:]}")
                    commit = run(["git", "commit", "-m", "feat: generate application with AI"], workspace, timeout=60)
                    if commit.returncode != 0:
                        raise RuntimeError(f"git commit failed: {commit.stderr[-2000:]}")
                    push = run(["git", "push", "--set-upstream", "origin", branch], workspace, timeout=180)
                    if push.returncode != 0:
                        raise RuntimeError(f"git push failed: {push.stderr[-2000:]}")
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
