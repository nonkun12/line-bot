#!/usr/bin/env python3
"""One-shot, explicitly invoked Mac worker for isolated local-fm review jobs.

No daemon, polling loop, file edits, commits, merges, or deployments. Without
--execute this program only prints a safety summary and does not claim a job.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ALLOWED_REPOSITORY = "nonkun12/line-bot"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_RESPONSE_BYTES = 64_000
HTTP_TIMEOUT_SECONDS = 15
LOCAL_REVIEW_TIMEOUT_SECONDS = 150


class WorkerError(RuntimeError):
    pass


def validate_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise WorkerError("bridge URL must use HTTPS (HTTP allowed only for localhost)")
    if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WorkerError("invalid bridge URL")
    return value.rstrip("/")


def validate_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise WorkerError("job payload must be an object")
    if payload.get("schema_version") != 1 or payload.get("kind") != "local_code_review":
        raise WorkerError("unsupported job payload")
    if payload.get("repository") != ALLOWED_REPOSITORY:
        raise WorkerError("repository is not allowlisted")
    for name in ("base_sha", "head_sha"):
        if not isinstance(payload.get(name), str) or not SHA_RE.fullmatch(payload[name]):
            raise WorkerError(f"invalid {name}")
    if payload["base_sha"] == payload["head_sha"]:
        raise WorkerError("base and head SHAs must differ")
    if set(payload) != {"schema_version", "kind", "repository", "base_sha", "head_sha"}:
        raise WorkerError("unexpected payload fields")
    return payload


def git(repo: Path, *args: str, timeout: int = 15) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkerError("git validation failed or timed out") from exc
    if proc.returncode:
        raise WorkerError("git validation failed")
    return proc.stdout.strip()


def verify_checkout(repo_path: str, payload: dict) -> Path:
    repo = Path(repo_path).expanduser().resolve(strict=True)
    if not repo.is_dir():
        raise WorkerError("configured repository path is not a directory")
    if git(repo, "rev-parse", "--show-toplevel") != str(repo):
        raise WorkerError("configured path is not the repository root")
    head = git(repo, "rev-parse", "HEAD")
    if head != payload["head_sha"]:
        raise WorkerError("checkout HEAD does not exactly match requested head_sha")
    for sha in (payload["base_sha"], payload["head_sha"]):
        resolved = git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}")
        if resolved != sha:
            raise WorkerError("requested SHA does not resolve to the exact commit")
    # Only review a base commit that is an ancestor of the requested head.
    try:
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor",
             payload["base_sha"], payload["head_sha"]],
            check=True, capture_output=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkerError("base SHA is not an ancestor of requested head") from exc
    return repo


def request_json(url: str, key: str, method: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    req = Request(
        url, data=data, method=method,
        headers={
            "Accept": "application/json",
            "X-Local-Review-Bridge-Key": key,
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise WorkerError("bridge response exceeded size limit")
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise WorkerError("bridge response must be a JSON object")
        return parsed
    except HTTPError as exc:
        # Do not print response bodies; they could contain internal data.
        raise WorkerError(f"bridge HTTP status {exc.code}") from exc
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerError("bridge request failed or returned invalid JSON") from exc


def run_once(base_url: str, key: str, repo_path: str, *, execute: bool) -> int:
    base_url = validate_base_url(base_url)
    if not key or len(key) > 512:
        raise WorkerError("LOCAL_REVIEW_BRIDGE_KEY is missing or invalid")
    if not execute:
        print("READY: no request made; rerun with --execute after explicit approval")
        return 0

    claimed = request_json(base_url + "/claim", key, "POST", {})
    job = claimed.get("job")
    if not claimed.get("ok"):
        raise WorkerError("bridge did not accept claim request")
    if job is None:
        print("NOT_RUN: no pending local review job")
        return 2
    if not isinstance(job, dict):
        raise WorkerError("bridge returned an invalid job envelope")
    job_id, token = job.get("id"), job.get("claim_token")
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
        raise WorkerError("invalid claimed job id")
    if not isinstance(token, str) or not token or len(token) > 256:
        raise WorkerError("invalid claim token")

    payload = validate_payload(job.get("payload"))
    report_body = {
        "job_id": job_id,
        "claim_token": token,
        "status": "NOT_RUN",
        "reason": "worker failed closed before review",
    }
    try:
        repo = verify_checkout(repo_path, payload)
        script = repo / "scripts" / "local_fm_code_review.py"
        if not script.is_file():
            raise WorkerError("local review script is missing")
        with tempfile.TemporaryDirectory(prefix="line-local-review-") as tmp:
            report_path = Path(tmp) / "report.json"
            try:
                proc = subprocess.run(
                    [sys.executable, str(script), "--base", payload["base_sha"],
                     "--head", payload["head_sha"], "--report", str(report_path)],
                    cwd=repo, check=False, capture_output=True, text=True,
                    timeout=LOCAL_REVIEW_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                raise WorkerError("local fm review timed out") from exc
            if proc.returncode not in {0, 1} or not report_path.is_file():
                raise WorkerError("local fm review returned NOT_RUN or no report")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                raise WorkerError("local fm report is not an object")
            # Validate the report's provenance before sending it to the server.
            if (report.get("base") != payload["base_sha"]
                    or report.get("head") != payload["head_sha"]
                    or report.get("status") != "REVIEWED"
                    or report.get("provider") != "local-fm"):
                raise WorkerError("local fm report provenance mismatch")
            if (proc.returncode == 0) != (report.get("verdict") == "PASS"):
                raise WorkerError("local fm exit code and verdict disagree")
            report_body = {
                "job_id": job_id, "claim_token": token,
                "status": "REVIEWED", "report": report,
            }
    except (WorkerError, OSError, ValueError, json.JSONDecodeError) as exc:
        # Bounded and sanitized: don't include prompts, diffs, tokens, or raw CLI output.
        report_body = {
            "job_id": job_id, "claim_token": token,
            "status": "NOT_RUN", "reason": str(exc)[:500],
        }

    completed = request_json(base_url + "/complete", key, "POST", report_body)
    if not completed.get("ok"):
        raise WorkerError("bridge rejected completion; inspect job status before retrying")
    state = completed.get("status")
    print("REVIEW SUBMITTED: " + str(state))
    return 0 if report_body["status"] == "REVIEWED" and report_body["report"]["verdict"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="explicitly claim and process at most one job")
    parser.add_argument("--repo-path", default=os.environ.get("LOCAL_REVIEW_REPO_PATH", ""))
    parser.add_argument("--bridge-url", default=os.environ.get("LOCAL_REVIEW_BRIDGE_URL", ""))
    args = parser.parse_args()
    try:
        if not args.bridge_url:
            raise WorkerError("LOCAL_REVIEW_BRIDGE_URL is required")
        if not args.repo_path:
            raise WorkerError("LOCAL_REVIEW_REPO_PATH is required")
        return run_once(
            args.bridge_url,
            os.environ.get("LOCAL_REVIEW_BRIDGE_KEY", ""),
            args.repo_path,
            execute=args.execute,
        )
    except WorkerError as exc:
        print(f"NOT_RUN: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
