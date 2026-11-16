"""CAS-backed, one-time consumption of RSI approval and budget claims.

Each claim purpose has an isolated replay ledger. Verification and durable
consumption are separate from worker execution; this module never starts work.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Mapping

from scripts.orca_rsi_trust_claims import (
    VerifiedTrustClaim,
    verify_budget_authorization,
    verify_task_approval,
)

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_LEDGER_KEYS = {
    "orca_rsi_task_approval": "rsi_task_approval_replay",
    "orca_rsi_budget_authorization": "rsi_budget_authorization_replay",
}
_MAX_LEDGER_ENTRIES = 10_000


class TrustClaimReplayRejected(ValueError):
    """Raised when a trust claim cannot be safely consumed exactly once."""


def _read_ledger(state: Any, key: str) -> dict[str, list[str]]:
    if not isinstance(state, dict):
        raise TrustClaimReplayRejected("trust_replay_snapshot_missing")
    raw = state.get(key, {"used_nonces": [], "used_attestation_hashes": []})
    if not isinstance(raw, dict) or set(raw) != {"used_nonces", "used_attestation_hashes"}:
        raise TrustClaimReplayRejected("trust_replay_ledger_invalid")
    nonces, hashes = raw["used_nonces"], raw["used_attestation_hashes"]
    if (not isinstance(nonces, list) or not isinstance(hashes, list)
            or any(not isinstance(x, str) or not 32 <= len(x) <= 256 for x in nonces)
            or any(not isinstance(x, str) or not _HEX_64.fullmatch(x) for x in hashes)
            or len(nonces) != len(set(nonces))
            or len(hashes) != len(set(hashes))
            or len(nonces) != len(hashes)):
        raise TrustClaimReplayRejected("trust_replay_ledger_invalid")
    if len(nonces) >= _MAX_LEDGER_ENTRIES:
        raise TrustClaimReplayRejected("trust_replay_ledger_full")
    return {"used_nonces": list(nonces), "used_attestation_hashes": list(hashes)}


def _consume_once(*, store: Any, snapshot: Any,
                  verified: VerifiedTrustClaim) -> dict[str, Any]:
    state = getattr(snapshot, "state", None)
    revision = state.get("revision") if isinstance(state, dict) else None
    if type(revision) is not int or revision < 0:
        raise TrustClaimReplayRejected("trust_replay_revision_invalid")
    ledger_key = _LEDGER_KEYS.get(verified.claim_type)
    if ledger_key is None:
        raise TrustClaimReplayRejected("trust_claim_type_not_consumable")
    ledger = _read_ledger(state, ledger_key)
    if verified.nonce in ledger["used_nonces"]:
        raise TrustClaimReplayRejected("trust_claim_nonce_replayed")
    if verified.claim_hash in ledger["used_attestation_hashes"]:
        raise TrustClaimReplayRejected("trust_claim_hash_replayed")

    next_state = copy.deepcopy(state)
    next_ledger = copy.deepcopy(ledger)
    next_ledger["used_nonces"].append(verified.nonce)
    next_ledger["used_attestation_hashes"].append(verified.claim_hash)
    next_state[ledger_key] = next_ledger
    next_state["revision"] = revision + 1

    # Exactly one CAS attempt. Conflicts propagate; callers must stop, not retry.
    persisted = store.write(
        snapshot=snapshot,
        next_state=next_state,
        expected_revision=revision,
    )
    return {
        "status": "TRUST_CLAIM_CONSUMED",
        "claim_type": verified.claim_type,
        "signer_id": verified.signer_id,
        "task_id": verified.task_id,
        "cycle_id": verified.cycle_id,
        "commit_sha": verified.commit_sha,
        "nonce": verified.nonce,
        "claim_hash": verified.claim_hash,
        "snapshot": persisted,
        "execution_started": False,
        "required_next_action": "separate_execution_gate_and_worker_checks",
    }


def verify_and_consume_task_approval_once(
    *, store: Any, snapshot: Any, claim: Any,
    keyring: Mapping[str, str | bytes], key_signer_map: Mapping[str, str],
    allowed_approvers: Any,
    repository: str, task_id: str, task_digest: str, cycle_id: str,
    commit_sha: str, now: datetime, implementer_id: str,
) -> dict[str, Any]:
    """Verify an approval and persist its one-time nonce/hash using CAS."""
    verified = verify_task_approval(
        claim, keyring=keyring, key_signer_map=key_signer_map,
        allowed_approvers=allowed_approvers,
        repository=repository, task_id=task_id, task_digest=task_digest,
        cycle_id=cycle_id, commit_sha=commit_sha, now=now,
        implementer_id=implementer_id,
    )
    return _consume_once(store=store, snapshot=snapshot, verified=verified)


def verify_and_consume_budget_authorization_once(
    *, store: Any, snapshot: Any, claim: Any,
    keyring: Mapping[str, str | bytes], key_signer_map: Mapping[str, str],
    allowed_issuers: Any,
    repository: str, task_id: str, task_digest: str, cycle_id: str,
    commit_sha: str, now: datetime, expected_budget_unit: str,
    resolved_evidence: Mapping[str, bytes] | None,
) -> dict[str, Any]:
    """Verify budget evidence and persist its one-time nonce/hash using CAS."""
    verified = verify_budget_authorization(
        claim, keyring=keyring, key_signer_map=key_signer_map,
        allowed_issuers=allowed_issuers,
        repository=repository, task_id=task_id, task_digest=task_digest,
        cycle_id=cycle_id, commit_sha=commit_sha, now=now,
        expected_budget_unit=expected_budget_unit,
        resolved_evidence=resolved_evidence,
    )
    return _consume_once(store=store, snapshot=snapshot, verified=verified)
