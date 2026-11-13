"""GitHub Git-data backed state store with non-force fast-forward CAS.

The state ref and JSON document must be provisioned before use. Missing state
fails closed; this adapter never initializes or clears Global HOLD.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from scripts.orca_github_state_ref import (
    RefWriteRejected, canonical_state_bytes, prepare_write, state_digest,
    verify_before_ref_update,
)


class StateStoreError(RuntimeError):
    pass


class StateConflict(StateStoreError):
    pass


@dataclass(frozen=True)
class StateSnapshot:
    ref_sha: str
    state: dict[str, Any]
    blob_sha: str


class GitHubStateStore:
    def __init__(self, *, token: str, repository: str, branch: str,
                 path: str, opener: Callable = urllib.request.urlopen):
        if not token or "/" not in repository or not branch or not path:
            raise StateStoreError("github_state_store_configuration_missing")
        self.token = token
        self.repository = repository
        self.branch = branch
        self.path = path
        self.opener = opener
        self.api = "https://api.github.com"

    @classmethod
    def from_env(cls):
        return cls(
            token=os.environ.get("GITHUB_TOKEN", ""),
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
            branch=os.environ.get("ORCA_STATE_BRANCH", "orca-state"),
            path=os.environ.get("ORCA_STATE_PATH", "state/queue.json"),
        )

    def _request(self, method: str, route: str, payload: dict | None = None):
        url = self.api + route
        data = None if payload is None else json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "orca-github-native-state-store",
            },
        )
        try:
            with self.opener(request, timeout=15) as response:
                return json.loads(response.read(2_000_000).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (409, 422):
                raise StateConflict("github_ref_fast_forward_conflict") from None
            raise StateStoreError("github_state_api_rejected_request") from None
        except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError):
            raise StateStoreError("github_state_api_unavailable_or_invalid") from None

    def read(self) -> StateSnapshot:
        repo = urllib.parse.quote(self.repository, safe="/")
        branch = urllib.parse.quote(self.branch, safe="")
        ref = self._request("GET", f"/repos/{repo}/git/ref/heads/{branch}")
        ref_sha = ref.get("object", {}).get("sha")
        if not isinstance(ref_sha, str) or len(ref_sha) != 40:
            raise StateStoreError("state_ref_missing_or_invalid")
        commit = self._request("GET", f"/repos/{repo}/git/commits/{ref_sha}")
        tree_sha = commit.get("tree", {}).get("sha")
        if not isinstance(tree_sha, str):
            raise StateStoreError("state_commit_tree_missing")
        path = urllib.parse.quote(self.path, safe="/")
        # Bind the document read to the immutable commit observed above.
        # Reading by branch name could mix a newer document with the older ref_sha.
        content = self._request("GET", f"/repos/{repo}/contents/{path}?ref={ref_sha}")
        if content.get("encoding") != "base64" or not isinstance(content.get("content"), str):
            raise StateStoreError("state_document_missing_or_invalid")
        try:
            raw = base64.b64decode(content["content"], validate=False)
            state = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError, json.JSONDecodeError):
            raise StateStoreError("state_document_unreadable") from None
        if not isinstance(state, dict):
            raise StateStoreError("state_document_invalid")
        return StateSnapshot(ref_sha, state, str(content.get("sha", "")))

    def write(self, *, snapshot: StateSnapshot, next_state: dict[str, Any],
              expected_revision: int) -> StateSnapshot:
        try:
            intent = prepare_write(
                expected_ref_sha=snapshot.ref_sha,
                current_state=snapshot.state,
                next_state=next_state,
                expected_revision=expected_revision,
                force=False,
            )
            verify_before_ref_update(
                intent=intent,
                observed_ref_sha=snapshot.ref_sha,
                observed_state=snapshot.state,
            )
        except RefWriteRejected as exc:
            raise StateConflict(str(exc)) from None

        repo = urllib.parse.quote(self.repository, safe="/")
        blob = self._request("POST", f"/repos/{repo}/git/blobs", {
            "content": base64.b64encode(canonical_state_bytes(next_state)).decode("ascii"),
            "encoding": "base64",
        })
        blob_sha = blob.get("sha")
        if not isinstance(blob_sha, str):
            raise StateStoreError("state_blob_create_failed")

        commit = self._request("GET", f"/repos/{repo}/git/commits/{snapshot.ref_sha}")
        base_tree = commit.get("tree", {}).get("sha")
        if not isinstance(base_tree, str):
            raise StateStoreError("state_base_tree_missing")
        tree = self._request("POST", f"/repos/{repo}/git/trees", {
            "base_tree": base_tree,
            "tree": [{"path": self.path, "mode": "100644", "type": "blob", "sha": blob_sha}],
        })
        tree_sha = tree.get("sha")
        if not isinstance(tree_sha, str):
            raise StateStoreError("state_tree_create_failed")
        new_commit = self._request("POST", f"/repos/{repo}/git/commits", {
            "message": f"orca state revision {expected_revision + 1}",
            "tree": tree_sha,
            "parents": [snapshot.ref_sha],
        })
        new_sha = new_commit.get("sha")
        if not isinstance(new_sha, str):
            raise StateStoreError("state_commit_create_failed")

        branch = urllib.parse.quote(self.branch, safe="")
        # force=false makes a concurrent sibling commit non-fast-forward and rejected.
        self._request("PATCH", f"/repos/{repo}/git/refs/heads/{branch}", {
            "sha": new_sha, "force": False,
        })
        verified = self.read()
        if verified.ref_sha != new_sha or state_digest(verified.state) != intent["next_state_sha256"]:
            raise StateConflict("state_read_after_write_verification_failed")
        return verified
