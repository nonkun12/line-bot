import copy
from dataclasses import dataclass

import pytest

from scripts.orca_rsi_trust_claim_replay import (
    TrustClaimReplayRejected,
    verify_and_consume_budget_authorization_once,
    verify_and_consume_task_approval_once,
)
import base64
import hashlib
import json
from datetime import datetime, timezone
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC = PRIVATE.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
KEYRING = {"approval-key-v1": PUBLIC, "budget-key-v1": PUBLIC}
KEY_SIGNER_MAP = {"approval-key-v1": "human-approver", "budget-key-v1": "budget-authority"}
REPO, TASK = "nonkun12/line-bot", "task-001"
TASK_DIGEST, CYCLE, COMMIT = "a" * 64, "b" * 64, "c" * 40


def _sign(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    signed = dict(value)
    signed["signature"] = base64.b64encode(PRIVATE.sign(raw)).decode()
    return signed


def _approval():
    return _sign({
        "claim_type": "orca_rsi_task_approval", "schema_version": 1,
        "key_id": "approval-key-v1", "repository": REPO, "task_id": TASK,
        "task_digest": TASK_DIGEST, "cycle_id": CYCLE, "commit_sha": COMMIT,
        "approver_id": "human-approver", "verdict": "APPROVED",
        "nonce": "d" * 32, "issued_at": "2026-11-16T11:59:00Z",
        "expires_at": "2026-11-16T12:05:00Z",
    })


def _budget(evidence):
    ref = "collector://bundle/42"
    bundle = len(ref.encode()).to_bytes(4, "big") + ref.encode() + len(evidence).to_bytes(8, "big") + evidence
    return _sign({
        "claim_type": "orca_rsi_budget_authorization", "schema_version": 1,
        "key_id": "budget-key-v1", "repository": REPO, "task_id": TASK,
        "task_digest": TASK_DIGEST, "cycle_id": CYCLE, "commit_sha": COMMIT,
        "issuer_id": "budget-authority", "budget_unit": "github_actions_minutes",
        "authorized_limit_units": 100, "observed_spend_units": 20,
        "remaining_units": 80, "evidence_refs": [ref],
        "evidence_sha256": hashlib.sha256(bundle).hexdigest(),
        "nonce": "e" * 32, "issued_at": "2026-11-16T11:59:00Z",
        "expires_at": "2026-11-16T12:04:00Z",
    })


@dataclass
class Snapshot:
    ref_sha: str
    state: dict


class FakeCASStore:
    def __init__(self):
        self.snapshot = Snapshot("c" * 40, {
            "schema_version": 1, "revision": 3, "global_hold": True,
            "emergency_stop": False, "tasks": [], "active_lease": None,
            "rsi_review_replay": {"used_nonces": [], "used_attestation_hashes": []},
            "rsi_task_approval_replay": {"used_nonces": [], "used_attestation_hashes": []},
            "rsi_budget_authorization_replay": {"used_nonces": [], "used_attestation_hashes": []},
        })
        self.writes = 0
        self.conflict = False

    def write(self, *, snapshot, next_state, expected_revision):
        self.writes += 1
        if self.conflict or snapshot.ref_sha != self.snapshot.ref_sha:
            raise RuntimeError("github_ref_fast_forward_conflict")
        if expected_revision != self.snapshot.state["revision"]:
            raise RuntimeError("stale_state_revision")
        self.snapshot = Snapshot("d" * 40, copy.deepcopy(next_state))
        return self.snapshot


def _consume_approval(store):
    return verify_and_consume_task_approval_once(
        store=store, snapshot=store.snapshot, claim=_approval(),
        keyring=KEYRING, key_signer_map=KEY_SIGNER_MAP,
        allowed_approvers=["human-approver"],
        repository=REPO, task_id=TASK, task_digest=TASK_DIGEST,
        cycle_id=CYCLE, commit_sha=COMMIT, now=NOW,
        implementer_id="worker-author",
    )


def _consume_budget(store):
    evidence = b"trusted collector evidence v1"
    return verify_and_consume_budget_authorization_once(
        store=store, snapshot=store.snapshot, claim=_budget(evidence),
        keyring=KEYRING, key_signer_map=KEY_SIGNER_MAP,
        allowed_issuers=["budget-authority"],
        repository=REPO, task_id=TASK, task_digest=TASK_DIGEST,
        cycle_id=CYCLE, commit_sha=COMMIT, now=NOW,
        expected_budget_unit="github_actions_minutes",
        resolved_evidence={"collector://bundle/42": evidence},
    )


def test_task_approval_consumed_once_before_execution():
    store = FakeCASStore()
    result = _consume_approval(store)
    assert result["status"] == "TRUST_CLAIM_CONSUMED"
    assert result["execution_started"] is False
    ledger = store.snapshot.state["rsi_task_approval_replay"]
    assert ledger["used_nonces"] == ["d" * 32]
    assert ledger["used_attestation_hashes"] == [result["claim_hash"]]
    assert store.writes == 1


def test_budget_authorization_has_separate_replay_ledger():
    store = FakeCASStore()
    approval = _consume_approval(store)
    assert store.snapshot.state["rsi_budget_authorization_replay"] == {
        "used_nonces": [], "used_attestation_hashes": []
    }
    result = _consume_budget(store)
    assert result["execution_started"] is False
    assert "rsi_task_approval_replay" in store.snapshot.state
    assert store.snapshot.state["rsi_budget_authorization_replay"]["used_nonces"] == [
        "e" * 32
    ]
    assert store.writes == 2


def test_replay_rejected_without_second_write():
    store = FakeCASStore()
    _consume_approval(store)
    with pytest.raises(TrustClaimReplayRejected, match="trust_claim_nonce_replayed"):
        _consume_approval(store)
    assert store.writes == 1


def test_cas_conflict_is_not_retried_and_invalid_claim_does_not_write():
    store = FakeCASStore()
    store.conflict = True
    with pytest.raises(RuntimeError, match="github_ref_fast_forward_conflict"):
        _consume_approval(store)
    assert store.writes == 1
    store = FakeCASStore()
    forged = _approval()
    forged["nonce"] = "f" * 32
    with pytest.raises(ValueError, match="claim_signature_invalid"):
        verify_and_consume_task_approval_once(
            store=store, snapshot=store.snapshot, claim=forged,
            keyring=KEYRING, key_signer_map=KEY_SIGNER_MAP,
            allowed_approvers=["human-approver"],
            repository=REPO, task_id=TASK, task_digest=TASK_DIGEST,
            cycle_id=CYCLE, commit_sha=COMMIT, now=NOW,
            implementer_id="worker-author",
        )
    assert store.writes == 0


def test_malformed_replay_ledger_fails_closed():
    store = FakeCASStore()
    store.snapshot.state["rsi_task_approval_replay"] = {
        "used_nonces": ["d" * 32], "used_attestation_hashes": []
    }
    with pytest.raises(TrustClaimReplayRejected, match="trust_replay_ledger_invalid"):
        _consume_approval(store)
    assert store.writes == 0


def test_budget_authorization_replay_is_rejected_without_second_write():
    store = FakeCASStore()
    _consume_budget(store)
    with pytest.raises(TrustClaimReplayRejected, match="trust_claim_nonce_replayed"):
        _consume_budget(store)
    assert store.writes == 1


def test_budget_cas_conflict_is_not_retried():
    store = FakeCASStore()
    store.conflict = True
    with pytest.raises(RuntimeError, match="github_ref_fast_forward_conflict"):
        _consume_budget(store)
    assert store.writes == 1


def test_missing_replay_ledger_fails_closed_without_initializing_it():
    store = FakeCASStore()
    del store.snapshot.state["rsi_task_approval_replay"]
    with pytest.raises(TrustClaimReplayRejected, match="trust_replay_ledger_missing"):
        _consume_approval(store)
    assert store.writes == 0
    assert "rsi_task_approval_replay" not in store.snapshot.state
