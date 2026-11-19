from __future__ import annotations

import hashlib
import io
import json
import zipfile

from core import rea_independent_verification_client as client
from core.rea_independent_verification import WORKFLOW_PATH

SHA = "a" * 40
RUN_ID = 987


def _archive():
    receipt = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "verified_sha": SHA,
        "base_sha": "b" * 40,
        "test_outcome": "SUCCESS",
        "identity_outcome": "SUCCESS",
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rea-independent-verification.json", json.dumps(receipt))
    return buffer.getvalue()


def test_client_downloads_only_exact_sha_run_bound_artifact(monkeypatch):
    archive = _archive()
    run = {
        "id": RUN_ID,
        "run_number": 22,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": "nonkun12/line-bot"},
        "path": WORKFLOW_PATH,
        "event": "push",
        "head_branch": "line-dev/987",
        "head_sha": SHA,
    }
    artifact = {
        "name": f"rea-independent-verification-{RUN_ID}",
        "expired": False,
        "archive_download_url": "https://api.github.com/archive.zip",
        "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
        "workflow_run": {"id": RUN_ID, "head_sha": SHA},
    }

    def fake_get(url, token, *, api=True):
        if "/actions/runs?" in url:
            return json.dumps({"workflow_runs": [run]}).encode()
        if url.endswith(f"/actions/runs/{RUN_ID}"):
            return json.dumps(run).encode()
        if url.endswith(f"/actions/runs/{RUN_ID}/artifacts?per_page=100"):
            return json.dumps({"artifacts": [artifact]}).encode()
        if url == artifact["archive_download_url"]:
            return archive
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(client, "_get", fake_get)
    receipt, metadata = client.load_independent_verification_for_sha(
        SHA, token="test-token"
    )
    assert receipt["run_id"] == RUN_ID
    assert metadata["head_sha"] == SHA


def test_client_rejects_artifact_digest_mismatch(monkeypatch):
    archive = _archive()
    run = {
        "id": RUN_ID,
        "run_number": 22,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": "nonkun12/line-bot"},
        "path": WORKFLOW_PATH,
        "event": "push",
        "head_branch": "line-dev/987",
        "head_sha": SHA,
    }
    artifact = {
        "name": f"rea-independent-verification-{RUN_ID}",
        "expired": False,
        "archive_download_url": "https://api.github.com/archive.zip",
        "digest": "sha256:" + "0" * 64,
        "workflow_run": {"id": RUN_ID, "head_sha": SHA},
    }

    def fake_get(url, token, *, api=True):
        if "/actions/runs?" in url:
            return json.dumps({"workflow_runs": [run]}).encode()
        if url.endswith(f"/actions/runs/{RUN_ID}"):
            return json.dumps(run).encode()
        if url.endswith(f"/actions/runs/{RUN_ID}/artifacts?per_page=100"):
            return json.dumps({"artifacts": [artifact]}).encode()
        if url == artifact["archive_download_url"]:
            return archive
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(client, "_get", fake_get)
    receipt, metadata = client.load_independent_verification_for_sha(
        SHA, token="test-token"
    )
    assert receipt is None
    assert metadata["id"] == RUN_ID


def test_client_requires_exact_sha_and_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert client.load_independent_verification_for_sha("not-a-sha", token="x") == (None, None)
    assert client.load_independent_verification_for_sha(SHA, token="") == (None, None)
