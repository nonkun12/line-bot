"""Run the GitHub CI + Worker-side AI review gate before merge approval."""

from __future__ import annotations

import os
import subprocess
from typing import Any

import requests

GITHUB_API = "https://api.github.com"
REQUIRED_WORKFLOWS = ("Pytest", "Overnight Worker Test", "AI Code Review")
AI_REVIEW_API = "https://api.groq.com/openai/v1/chat/completions"
AI_REVIEW_MODEL = os.environ.get("AI_REVIEW_MODEL", "openai/gpt-oss-20b")
AI_REVIEW_MAX_DIFF_CHARS = int(os.environ.get("AI_REVIEW_MAX_DIFF_CHARS", "120000"))


def _repo() -> str:
    return (
        os.environ.get("GITHUB_REPO")
        or os.environ.get("AI_REPORT_GITHUB_REPO")
        or "nonkun12/line-bot"
    )


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _head_sha(state: dict[str, Any]) -> str | None:
    publish = state.get("publish_result") or {}
    commit = state.get("commit_result") or {}
    return commit.get("hash") or publish.get("commit_hash")


def _review_diff(state: dict[str, Any]) -> str:
    workdir = state.get("workdir")
    if not workdir or not os.path.isdir(workdir):
        raise RuntimeError("Job worktree is missing for AI review")
    result = subprocess.run(
        ["git", "diff", "origin/main...HEAD"],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed during AI review")
    if not result.stdout.strip():
        raise RuntimeError("AI review diff is empty")
    return result.stdout[:AI_REVIEW_MAX_DIFF_CHARS]


def _call_ai_review(diff: str) -> dict[str, Any]:
    token = os.environ.get("GROQ_API_KEY", "").strip()
    if not token:
        raise RuntimeError("GROQ_API_KEY is not configured for Worker AI review")

    prompt = f"""You are the blocking senior reviewer for an autonomous development Worker.
Review ONLY the pull-request diff below. Look for correctness, security, regressions,
concurrency/lease issues, approval/deploy bypasses, GitHub workflow problems, and any
regression risk to existing LINE Notes/Memory/Reminder behavior.

Return JSON only:
{{
  \"verdict\": \"PASS\" | \"FAIL\",
  \"summary\": \"one concise paragraph\",
  \"findings\": [
    {{\"severity\": \"blocking\" | \"warning\", \"file\": \"path\", \"detail\": \"actionable finding\"}}
  ]
}}

Use FAIL only when a finding should block merge. Do not invent issues unrelated to the diff.

PULL REQUEST DIFF:
{diff}
"""
    payload = {
        "model": AI_REVIEW_MODEL,
        "messages": [
            {"role": "system", "content": "You are a strict senior software engineer. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 1400,
    }
    response = requests.post(
        AI_REVIEW_API,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Groq AI review failed: HTTP {response.status_code}")
    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("Groq AI review returned no content")
    if content.startswith("```"):
        content = content.removeprefix("```").removesuffix("```").strip()
        if content.startswith("json"):
            content = content[4:].lstrip()
    review = __import__("json").loads(content)
    if review.get("verdict") not in {"PASS", "FAIL"}:
        raise RuntimeError("AI review returned an invalid verdict")
    return review


def check_github_review_status(state: dict[str, Any]) -> dict[str, Any]:
    """Check all required GitHub workflow results for the Job commit."""
    head_sha = _head_sha(state)
    if not head_sha:
        return {"status": "failed", "reason": "approved Job commit hash is missing"}

    response = requests.get(
        f"{GITHUB_API}/repos/{_repo()}/actions/runs",
        headers=_headers(),
        params={"head_sha": head_sha, "per_page": 50},
        timeout=15,
    )
    if response.status_code != 200:
        return {"status": "pending", "reason": f"GitHub workflow lookup failed: HTTP {response.status_code}"}

    runs = response.json()
    by_name: dict[str, dict[str, Any]] = {}
    if isinstance(runs, dict):
        runs = runs.get("workflow_runs", [])
    for run in runs if isinstance(runs, list) else []:
        name = run.get("name")
        if name in REQUIRED_WORKFLOWS and name not in by_name:
            by_name[name] = run

    missing = [name for name in REQUIRED_WORKFLOWS if name not in by_name]
    if missing:
        return {"status": "pending", "reason": "required GitHub review checks are not present", "missing": missing}

    pending = [name for name, run in by_name.items() if run.get("status") != "completed"]
    if pending:
        return {"status": "pending", "reason": "required GitHub review checks are still running", "pending": pending}

    failed = [name for name, run in by_name.items() if run.get("conclusion") not in {"success", "neutral", "skipped"}]
    if failed:
        return {"status": "failed", "reason": "one or more required GitHub review checks failed", "failed": failed}

    return {
        "status": "passed",
        "head_sha": head_sha,
        "workflows": {
            name: {"run_id": run.get("id"), "status": run.get("status"), "conclusion": run.get("conclusion")}
            for name, run in by_name.items()
        },
    }


def check_review_status(state: dict[str, Any]) -> dict[str, Any]:
    """Combine GitHub CI results with an actual Worker-side AI review."""
    github_result = check_github_review_status(state)
    if github_result.get("status") != "passed":
        return github_result
    try:
        ai_result = _call_ai_review(_review_diff(state))
    except RuntimeError as exc:
        return {"status": "failed", "reason": str(exc)}
    except requests.RequestException as exc:
        return {"status": "pending", "reason": f"Groq review request failed: {exc}"}
    except Exception as exc:
        return {"status": "failed", "reason": f"AI review error: {exc}"}

    if ai_result.get("verdict") != "PASS":
        return {
            "status": "failed",
            "reason": ai_result.get("summary") or "AI review rejected the Job",
            "ai_review": ai_result,
            "github": github_result,
        }
    return {"status": "passed", "github": github_result, "ai_review": ai_result}


def review_node(state: dict[str, Any]) -> dict[str, Any]:
    results = dict(state.get("agent_results", {}))
    try:
        review_result = check_review_status(state)
    except requests.RequestException as exc:
        review_result = {"status": "pending", "reason": f"GitHub review request failed: {exc}"}
    except Exception as exc:
        review_result = {"status": "failed", "reason": f"review agent error: {exc}"}
    results["review"] = review_result
    return {**state, "agent_results": results, "review_result": review_result}
