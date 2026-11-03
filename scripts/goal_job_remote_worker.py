"""Authenticated GitHub Actions worker for Render-backed Goal child JOBs.

Claims one job, runs the existing guarded runtime, publishes its branch, waits
for exact-SHA test and independent-review workflows, then reports evidence.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

API_BASE = os.environ.get("GOAL_JOB_API_BASE_URL", "https://line-bot-yvea.onrender.com").rstrip("/")
INTERNAL_KEY = os.environ.get("INTERNAL_PUSH_KEY", "")
REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "nonkun12/line-bot")
TIMEOUT_SECONDS = int(os.environ.get("GOAL_JOB_VERIFY_TIMEOUT_SECONDS", "900"))


def _api(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not INTERNAL_KEY:
        raise RuntimeError("INTERNAL_PUSH_KEY is not configured")
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{path}", data=body, method="POST",
        headers={"Content-Type": "application/json", "x-internal-key": INTERNAL_KEY},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Goal API request failed: {type(exc).__name__}") from exc
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise RuntimeError("Goal API rejected the request")
    return data


def _run(*args: str, timeout: int = 60) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout)[-1500:]
        raise RuntimeError(f"command failed ({args[0]}): {detail}")
    return result.stdout.strip()


def _workflow_run(workflow: str, branch: str, target_sha: str) -> dict[str, Any]:
    _run("gh", "workflow", "run", workflow, "--ref", branch)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    seen: set[int] = set()
    while time.monotonic() < deadline:
        raw = _run(
            "gh", "run", "list", "--workflow", workflow, "--branch", branch,
            "--limit", "10", "--json", "databaseId,url,status,conclusion,headSha",
        )
        runs = json.loads(raw or "[]")
        for run in runs:
            if run.get("headSha") != target_sha:
                continue
            run_id = run.get("databaseId")
            if not isinstance(run_id, int):
                continue
            seen.add(run_id)
            if run.get("status") == "completed":
                return {
                    "id": run_id,
                    "url": run.get("url", ""),
                    "success": run.get("conclusion") == "success",
                }
        time.sleep(10)
    raise TimeoutError(f"{workflow} did not complete for the target SHA")


def _report_failure(job_id: int, claim_token: str, message: str) -> None:
    try:
        _api("/internal/goal-jobs/complete", {
            "job_id": job_id, "claim_token": claim_token, "success": False,
            "last_error": message[:1800],
        })
    except Exception as exc:
        print(f"Failure report could not be delivered: {type(exc).__name__}", file=sys.stderr)


def main() -> int:
    claim = _api("/internal/goal-jobs/claim", {})
    if claim.get("claimed") is not True:
        print("No pending Goal child JOB.")
        return 0
    job = claim.get("job")
    if not isinstance(job, dict) or type(job.get("id")) is not int:
        raise RuntimeError("Claim response is malformed")
    job_id = job["id"]
    claim_token = job.get("claim_token")
    payload = job.get("payload")
    if not isinstance(claim_token, str) or not claim_token or not isinstance(payload, dict):
        raise RuntimeError("Claim response is missing required fields")

    try:
        from scripts.goal_job_runtime_adapter import execute_goal_child

        output = execute_goal_child(job, payload)
        evidence = output.get("evidence")
        if not isinstance(evidence, dict):
            raise RuntimeError("Guarded runtime returned no evidence")
        produced_sha = evidence.get("produced_sha")
        branch = evidence.get("branch")
        checks = evidence.get("checks")
        if (
            not isinstance(produced_sha, str) or len(produced_sha) != 40
            or not isinstance(branch, str) or not branch.startswith("line-dev/")
            or not isinstance(checks, list)
            or not all(isinstance(item, dict) and item.get("status") == "PASS" for item in checks)
        ):
            raise RuntimeError("Guarded runtime evidence did not pass its contract")

        _run("git", "diff", "--check", f"{evidence['base_sha']}..{produced_sha}")
        _run("git", "push", "--set-upstream", "origin", f"HEAD:refs/heads/{branch}")
        pytest = _workflow_run("pytest.yml", branch, produced_sha)
        review = _workflow_run("independent-code-review.yml", branch, produced_sha)
        verification = {
            "target_sha": produced_sha,
            "pytest_status": "PASS" if pytest["success"] else "FAIL",
            "review_status": "PASS" if review["success"] else "FAIL",
            "pytest_run_url": pytest["url"],
            "review_run_url": review["url"],
        }
        evidence["verification"] = verification
        all_pass = pytest["success"] and review["success"]
        if not all_pass:
            raise RuntimeError("Exact-SHA pytest or independent review failed")
        response = _api("/internal/goal-jobs/complete", {
            "job_id": job_id, "claim_token": claim_token, "success": True,
            "result": output["result"], "evidence": evidence,
        })
        print(json.dumps({"job_id": job_id, "completed": response.get("completed"), "sha": produced_sha}))
        return 0
    except Exception as exc:
        message = f"{type(exc).__name__}: {str(exc)}"
        _report_failure(job_id, claim_token, message)
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
