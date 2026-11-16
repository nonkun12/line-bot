"""CAS-backed, one-time consumption of signed RSI review attestations.

This adapter writes the replay marker into the already-provisioned Orca
GitHub state document using the store's non-force compare-and-swap write.
A failed/stale write blocks continuation; it never retries against a newer
snapshot automatically.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Iterable

from scripts.orca_rsi_review_attestation import (
    ReviewAttestationRejected,
    verify_independent_review,
)

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_LEDGER_KEY = "rsi_review_replay"
_MAX_LEDGER_ENTRIES = 10_000


class ReviewReplayStateRejected(ValueError):
    """Raised when durable replay state is missing, malformed, or conflicting."""


def _ledger(state: Any) -> dict[str, list[str]]:
    if not isinstance(state, dict):
        raise ReviewReplayStateRejected("review_replay_state_invalid")
    raw = state.get(_LEDGER_KEY, {"used_nonces": [], "used_attestation_hashes": []})
    if not isinstance(raw, dict) or set(raw) != {"used_nonces", "used_attestation_hashes"}:
        raise ReviewReplayStateRejected("review_replay_ledger_invalid")
    nonces = raw["used_nonces"]
    hashes = raw["used_attestation_hashes"]
    if (not isinstance(nonces, list) or not isinstance(hashes, list)
            or any(not isinstance(item, str) or not 16 <= len(item) <= 256 for item in nonces)
            or any(not isinstance(item, str) or not _HEX_64.fullmatch(item) for item in hashes)
            or len(nonces) != len(set(nonces))
            or len(hashes) != len(set(hashes))):
        raise ReviewReplayStateRejected("review_replay_ledger_invalid")
    if len(nonces) != len(hashes):
        raise ReviewReplayStateRejected("review_replay_ledger_invalid")
    if len(nonces) > _MAX_LEDGER_ENTRIES:
        raise ReviewReplayStateRejected("review_replay_ledger_full")
    return {"used_nonces": list(nonces), "used_attestation_hashes": list(hashes)}


def verify_and_consume_review_once(
    *,
    store: Any,
    snapshot: Any,
    attestation: Any,
    public_key_pem: str | bytes,
    repository: str,
    cycle_id: str,
    commit_sha: str,
    expected_nonce: str,
    allowed_reviewers: Iterable[str],
    implementer_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Verify a review and atomically persist its nonce/hash before work starts.

    The store must implement write(snapshot=..., next_state=...,
    expected_revision=...) with non-force CAS semantics. If a concurrent
    writer wins, the conflict propagates and the caller must stop and reread
    through its normal orchestration path; this function never retries.
    """
    state = getattr(snapshot, "state", None)
    if not isinstance(state, dict):
        raise ReviewReplayStateRejected("review_replay_snapshot_missing")
    revision = state.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ReviewReplayStateRejected("review_replay_revision_invalid")
    ledger = _ledger(state)
    if expected_nonce in ledger["used_nonces"]:
        raise ReviewReplayStateRejected("review_nonce_replayed")
    if len(ledger["used_nonces"]) >= _MAX_LEDGER_ENTRIES:
        raise ReviewReplayStateRejected("review_replay_ledger_full")

    try:
        verified = verify_independent_review(
            attestation,
            public_key_pem,
            repository=repository,
            cycle_id=cycle_id,
            commit_sha=commit_sha,
            expected_nonce=expected_nonce,
            used_attestation_hashes=ledger["used_attestation_hashes"],
            now=now,
            allowed_reviewers=allowed_reviewers,
        )
    except ReviewAttestationRejected as exc:
        raise ReviewReplayStateRejected(str(exc)) from None
    if verified.attestation_hash in ledger["used_attestation_hashes"]:
        raise ReviewReplayStateRejected("review_attestation_replayed")

    next_state = copy.deepcopy(state)
    next_ledger = copy.deepcopy(ledger)
    next_ledger["used_nonces"].append(verified.nonce)
    next_ledger["used_attestation_hashes"].append(verified.attestation_hash)
    next_state[_LEDGER_KEY] = next_ledger
    next_state["revision"] = revision + 1

    persisted = store.write(
        snapshot=snapshot,
        next_state=next_state,
        expected_revision=revision,
    )
    return {
        "status": "REVIEW_CONSUMED",
        "reviewer_id": verified.reviewer_id,
        "cycle_id": verified.cycle_id,
        "commit_sha": verified.commit_sha,
        "nonce": verified.nonce,
        "attestation_hash": verified.attestation_hash,
        "snapshot": persisted,
        "execution_started": False,
        "required_next_action": "separate_execution_gate_and_worker_checks",
    }
