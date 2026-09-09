"""Run the GitHub CI + Worker-side AI review gate before merge approval."""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

import requests

GITHUB_API = "https://api.github.com"
REQUIRED_WORKFLOWS = ("Pytest", "Overnight Worker Test", "AI Code Review")
AI_REVIEW_API = "https://api.groq.com/openai/v1/chat/completions"
AI_REVIEW_MODEL = os.environ.get("AI_REVIEW_MODEL", "openai/gpt-oss-20b")
AI_REVIEW_MAX_DIFF_CHARS = int(os.environ.get("AI_REVIEW_MAX_DIFF_CHARS", "120000"))
MAX_AI_REVIEW_RETRIES = int(os.environ.get("MAX_AI_REVIEW_RETRIES", "2"))
CI_POLL_INTERVAL_SECONDS = float(os.environ.get("CI_POLL_INTERVAL_SECONDS", "30"))


def _repo() -> str:
    return os.environ.get("GITHUB_REPO") or os.environ.get("AI_REPORT_GITHUB_REPO") or "nonkun12/line-bot"


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _head_sha(state: dict[str, Any]) -> str | None:
    commit = state.get("commit_result") or {}
    return commit.get("sha") or commit.get("hash") or state.get("head_sha")


def _review_diff(state: dict[str, Any]) -> str:
    workdir = str(state.get("workdir") or os.getcwd())
    result = subprocess.run(["git", "diff", "HEAD~1..HEAD"], cwd=workdir, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return result.stdout[:AI_REVIEW_MAX_DIFF_CHARS]


def _call_ai_review(diff: str) -> dict[str, Any]:
    token = os.environ.get("GROQ_API_KEY")
    if not token:
        raise RuntimeError("GROQ_API_KEY is not configured")
    prompt = f"Review this software change for correctness and security. Return JSON with verdict PASS or FAIL and summary.\n\nDIFF:\n{diff}"
    payload = {"model": AI_REVIEW_MODEL, "messages": [{"role": "system", "content": "You are a strict senior software engineer. Output JSON only."}, {"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 1400}
    response = requests.post(AI_REVIEW_API, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload, timeout=60)
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
    review = json.loads(content)
    if review.get("verdict") not in {"PASS", "FAIL"}:
        raise RuntimeError("AI review returned an invalid verdict")
    return review


def check_github_review_status(state: dict[str, Any]) -> dict[str, Any]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return {"status": "failed", "reason": "GITHUB_TOKEN is not configured"}
    head_sha = _head_sha(state)
    if not head_sha:
        return {"status": "failed", "reason": "approved Job commit hash is missing"}
    response = requests.get(f"{GITHUB_API}/repos/{_repo()}/actions/runs", headers=_headers(), params={"head_sha": head_sha, "per_page": 50}, timeout=15)
    if response.status_code != 200:
        time.sleep(CI_POLL_INTERVAL_SECONDS)
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
        time.sleep(CI_POLL_INTERVAL_SECONDS)
        return {"status": "pending", "reason": "required GitHub review checks are not present", "missing": missing}
    pending = [name for name, run in by_name.items() if run.get("status") != "completed"]
    if pending:
        time.sleep(CI_POLL_INTERVAL_SECONDS)
        return {"status": "pending", "reason": "required GitHub review checks are still running", "pending": pending}
    failed = [name for name, run in by_name.items() if run.get("conclusion") not in {"success", "neutral", "skipped"}]
    if failed:
        return {"status": "failed", "reason": "one or more required GitHub review checks failed", "failed": failed}
    return {"status": "passed", "head_sha": head_sha, "workflows": {name: {"run_id": run.get("id"), "status": run.get("status"), "conclusion": run.get("conclusion")} for name, run in by_name.items()}}


def check_review_status(state: dict[str, Any]) -> dict[str, Any]:
    github_result = check_github_review_status(state)
    if github_result.get("status") != "passed":
        return github_result
    try:
        ai_result = _call_ai_review(_review_diff(state))
    except requests.RequestException as exc:
        return {"status": "pending", "reason": f"Groq review request failed: {exc}"}
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)}
    if ai_result.get("verdict") != "PASS":
        retry_count = int(state.get("review_retry_count") or 0)
        return {"status": "failed", "retryable": retry_count < MAX_AI_REVIEW_RETRIES, "reason": ai_result.get("summary") or "AI review rejected the Job", "ai_review": ai_result, "github": github_result}
    return {"status": "passed", "github": github_result, "ai_review": ai_result}


def review_node(state: dict[str, Any]) -> dict[str, Any]:
    results = dict(state.get("agent_results", {}))
    try:
        review_result = check_review_status(state)
    except requests.RequestException as exc:
        review_result = {"status": "pending", "reason": f"GitHub review request failed: {exc}"}
    except Exception as exc:
        review_result = {"status": "failed", "reason": f"review agent error: {exc}"}
    next_state = {**state, "agent_results": results, "review_result": review_result}
    if review_result.get("status") == "failed" and review_result.get("ai_review") and review_result.get("retryable"):
        next_state["review_retry_count"] = int(state.get("review_retry_count") or 0) + 1
    results["review"] = review_result
    return {**next_state, "agent_results": results}
