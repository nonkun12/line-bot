"""Entry point for AI app generation with an empty-repository base branch."""
from __future__ import annotations

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
    ask,
    run,
    run_tests,
    slugify,
    validate_files,
    write_files,
)


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
                # Existing files in the independent app repository may be
                # artifacts from a previous failed generation or an earlier
                # generated version. Rewrite only the model-selected files on
                # this isolated development branch; main is never written here.
                written = write_files(workspace, files, replace_existing=True)
                generated_paths = set(written)
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