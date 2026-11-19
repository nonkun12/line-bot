"""Read a SHA-matched independent REA receipt from GitHub Actions.

This is read-only. Missing credentials, API errors, stale artifacts, mismatched
run identity, or malformed archives return no evidence and never grant authority.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Any

from core.rea_independent_verification import (
    REPOSITORY,
    WORKFLOW_PATH,
    evaluate_independent_verification_receipt,
)

MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024


def _get(url: str, token: str, *, api: bool = True) -> bytes:
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "line-bot-rea-verifier"}
    if api:
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=15) as response:
        data = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("response_size_limit")
    return data


def _api_url(api_url: str, path: str) -> str:
    return api_url.rstrip("/") + "/repos/" + REPOSITORY + path


def load_independent_verification_for_sha(
    expected_sha: str,
    *,
    token: str | None = None,
    repository: str = REPOSITORY,
    api_url: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (receipt, trusted_run_metadata) for the newest exact-SHA run.

    Both returned values are None when no matching run is available. If a run
    exists but its artifact is missing or invalid, metadata is returned with a
    None receipt so the evaluator remains UNKNOWN rather than accepting stale data.
    """
    if repository != REPOSITORY:
        return None, None
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        return None, None
    auth = token or os.environ.get("GITHUB_TOKEN", "")
    if not auth:
        return None, None
    base_url = (api_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
    try:
        query = urllib.parse.urlencode({"head_sha": expected_sha, "per_page": 100})
        runs_data = json.loads(_get(_api_url(base_url, "/actions/runs?" + query), auth))
        runs = runs_data.get("workflow_runs", []) if isinstance(runs_data, dict) else []
        candidates = [
            item for item in runs
            if isinstance(item, dict)
            and item.get("path") == WORKFLOW_PATH
            and item.get("head_sha") == expected_sha
        ]
        if not candidates:
            return None, None
        candidates.sort(key=lambda item: (item.get("run_number", 0), item.get("id", 0)), reverse=True)
        listed = candidates[0]
        run_id = listed.get("id")
        if not isinstance(run_id, int):
            return None, None

        metadata = json.loads(_get(_api_url(base_url, f"/actions/runs/{run_id}"), auth))
        if not isinstance(metadata, dict):
            return None, None
        if metadata.get("id") != run_id or metadata.get("head_sha") != expected_sha:
            return None, None
        if metadata.get("path") != WORKFLOW_PATH:
            return None, None
        if metadata.get("status") != "completed" or metadata.get("conclusion") != "success":
            return {}, metadata

        artifacts_data = json.loads(_get(_api_url(base_url, f"/actions/runs/{run_id}/artifacts?per_page=100"), auth))
        artifacts = artifacts_data.get("artifacts", []) if isinstance(artifacts_data, dict) else []
        artifact_name = f"rea-independent-verification-{run_id}"
        matching = [
            item for item in artifacts
            if isinstance(item, dict)
            and item.get("name") == artifact_name
            and item.get("expired") is False
            and isinstance(item.get("archive_download_url"), str)
            and isinstance(item.get("workflow_run"), dict)
            and item["workflow_run"].get("id") == run_id
            and item["workflow_run"].get("head_sha") == expected_sha
        ]
        if len(matching) != 1:
            return None, metadata
        artifact = matching[0]
        archive = _get(artifact["archive_download_url"], auth, api=False)
        digest = artifact.get("digest")
        if isinstance(digest, str) and digest.startswith("sha256:"):
            if hashlib.sha256(archive).hexdigest() != digest.split(":", 1)[1]:
                return None, metadata

        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = [name for name in bundle.namelist() if not name.endswith("/")]
            if names != ["rea-independent-verification.json"]:
                return None, metadata
            info = bundle.getinfo(names[0])
            if info.file_size > MAX_RECEIPT_BYTES:
                return None, metadata
            receipt = json.loads(bundle.read(info).decode("utf-8"))
        if not isinstance(receipt, dict):
            return None, metadata
        evaluated = evaluate_independent_verification_receipt(
            receipt, metadata, expected_sha=expected_sha
        )
        if evaluated.get("tests") not in {"PASS", "FAIL", "NOT_RUN"}:
            return None, metadata
        return receipt, metadata
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            urllib.error.URLError, zipfile.BadZipFile):
        return None, None


__all__ = ["load_independent_verification_for_sha"]
