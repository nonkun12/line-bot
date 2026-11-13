"""Fail-closed contract for append-only Git ref state persistence.

This module prepares and validates write intents. The caller must perform the
GitHub API operations with a token and must use a non-force ref update. This
module does not make network calls and is not itself a transactional store.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_SHA = re.compile(r"^[0-9a-f]{40}$")


class RefWriteRejected(ValueError):
    pass


def canonical_state_bytes(state: dict[str, Any]) -> bytes:
    if not isinstance(state, dict):
        raise RefWriteRejected("state_invalid")
    try:
        return json.dumps(state, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise RefWriteRejected("state_not_canonicalizable") from None


def state_digest(state: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_state_bytes(state)).hexdigest()


def prepare_write(*, expected_ref_sha: str, current_state: dict[str, Any],
                  next_state: dict[str, Any], expected_revision: int,
                  force: bool = False) -> dict[str, Any]:
    if not isinstance(expected_ref_sha, str) or not _SHA.fullmatch(expected_ref_sha):
        raise RefWriteRejected("expected_ref_sha_invalid")
    if force is not False:
        raise RefWriteRejected("force_update_forbidden")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise RefWriteRejected("expected_revision_invalid")
    current_revision = current_state.get("revision")
    next_revision = next_state.get("revision")
    if current_revision != expected_revision:
        raise RefWriteRejected("stale_state_revision")
    if not isinstance(next_revision, int) or isinstance(next_revision, bool):
        raise RefWriteRejected("next_revision_invalid")
    if next_revision != expected_revision + 1:
        raise RefWriteRejected("revision_must_increment_once")
    if next_state.get("schema_version") != current_state.get("schema_version"):
        raise RefWriteRejected("schema_version_change_forbidden")
    return {
        "expected_ref_sha": expected_ref_sha,
        "parent_commit_sha": expected_ref_sha,
        "force": False,
        "expected_revision": expected_revision,
        "next_revision": next_revision,
        "current_state_sha256": state_digest(current_state),
        "next_state_sha256": state_digest(next_state),
    }


def verify_before_ref_update(*, intent: dict[str, Any], observed_ref_sha: str,
                             observed_state: dict[str, Any]) -> None:
    if not isinstance(intent, dict):
        raise RefWriteRejected("write_intent_invalid")
    if observed_ref_sha != intent.get("expected_ref_sha"):
        raise RefWriteRejected("ref_moved_retry_from_fresh_state")
    if state_digest(observed_state) != intent.get("current_state_sha256"):
        raise RefWriteRejected("persisted_state_changed")
    if observed_state.get("revision") != intent.get("expected_revision"):
        raise RefWriteRejected("persisted_revision_changed")
    if intent.get("force") is not False or intent.get("parent_commit_sha") != observed_ref_sha:
        raise RefWriteRejected("unsafe_ref_update_intent")
