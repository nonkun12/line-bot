import base64
import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.orca_rsi_review_replay import (
    ReviewReplayStateRejected,
    verify_and_consume_review_once,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
NONCE = "one-time-challenge-nonce-123456"
CYCLE = "a" * 64
COMMIT = "b" * 40
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC = PRIVATE.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()


@dataclass
class Snapshot:
    ref_sha: str
    state: dict


class FakeCASStore:
    def __init__(self):
        self.snapshot = Snapshot("c" * 40, {
            "schema_version": 1, "revision": 3, "global_hold": True,
            "emergency_stop": False, "tasks": [], "active_lease": None,
            "consumed_approval_ids": [],
        })
        self.writes = 0
        self.conflict = False

    def write(self, *, snapshot, next_state, expected_revision):
        self.writes += 1
        if self.conflict or snapshot.ref_sha != self.snapshot.ref_sha:
            raise RuntimeError("github_ref_fast_forward_conflict")
        if expected_revision != self.snapshot.state["revision"]:
            raise RuntimeError("stale_state_revision")
        if next_state["revision"] != expected_revision + 1:
            raise RuntimeError("revision_must_increment_once")
        self.snapshot = Snapshot("d" * 40, copy.deepcopy(next_state))
        return self.snapshot


def _attestation(**overrides):
    value = {
        "schema_version": 1, "repository": "nonkun12/line-bot",
        "cycle_id": CYCLE, "commit_sha": COMMIT,
        "reviewer_id": "trusted-reviewer", "verdict": "PASS",
        "evidence_refs": ["actions://review/123"], "reviewed_at": NOW.isoformat(),
        "nonce": NONCE,
    }
    value.update(overrides)
    value["signature"] = base64.b64encode(PRIVATE.sign(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode())).decode()
    return value


def _consume(store, snapshot=None, attestation=None, nonce=NONCE):
    return verify_and_consume_review_once(
        store=store, snapshot=snapshot or store.snapshot,
        attestation=attestation or _attestation(), public_key_pem=PUBLIC,
        repository="nonkun12/line-bot", cycle_id=CYCLE, commit_sha=COMMIT,
        expected_nonce=nonce, allowed_reviewers=["trusted-reviewer"],
        public_key_reviewer_id="trusted-reviewer",
        implementer_id="worker-author", now=NOW,
    )


def test_valid_review_is_persisted_with_single_cas_before_execution():
    store = FakeCASStore()
    result = _consume(store)
    assert result["status"] == "REVIEW_CONSUMED"
    assert result["execution_started"] is False
    assert result["required_next_action"] == "separate_execution_gate_and_worker_checks"
    assert store.writes == 1
    ledger = store.snapshot.state["rsi_review_replay"]
    assert ledger["used_nonces"] == [NONCE]
    assert ledger["used_attestation_hashes"] == [result["attestation_hash"]]
    assert store.snapshot.state["revision"] == 4


def test_same_nonce_cannot_be_consumed_twice_even_with_different_signature():
    store = FakeCASStore()
    _consume(store)
    new_nonce_attestation = _attestation(nonce=NONCE)
    with pytest.raises(ReviewReplayStateRejected, match="review_nonce_replayed"):
        _consume(store, attestation=new_nonce_attestation)
    assert store.writes == 1


def test_same_attestation_hash_cannot_be_consumed_twice():
    store = FakeCASStore()
    _consume(store)
    with pytest.raises(ReviewReplayStateRejected, match="review_nonce_replayed"):
        _consume(store)
    assert store.writes == 1


def test_cas_conflict_blocks_and_does_not_retry():
    store = FakeCASStore()
    store.conflict = True
    with pytest.raises(RuntimeError, match="github_ref_fast_forward_conflict"):
        _consume(store)
    assert store.writes == 1


def test_invalid_signature_does_not_write_state():
    store = FakeCASStore()
    forged = _attestation()
    forged["evidence_refs"] = ["actions://tampered"]
    with pytest.raises(ValueError, match="review_signature_invalid"):
        _consume(store, attestation=forged)
    assert store.writes == 0


def test_malformed_persisted_ledger_fails_closed():
    store = FakeCASStore()
    store.snapshot.state["rsi_review_replay"] = {
        "used_nonces": [NONCE], "used_attestation_hashes": []
    }
    with pytest.raises(ReviewReplayStateRejected, match="review_replay_ledger_invalid"):
        _consume(store)
    assert store.writes == 0


def test_ledger_limit_fails_closed_without_pruning_history():
    store = FakeCASStore()
    store.snapshot.state["rsi_review_replay"] = {
        "used_nonces": [f"nonce-value-{i:04d}-xxxxxxxx" for i in range(10_000)],
        "used_attestation_hashes": [f"{i:064x}" for i in range(10_000)],
    }
    with pytest.raises(ReviewReplayStateRejected, match="review_replay_ledger_full|review_replay_ledger_inconsistent_or_full"):
        _consume(store)
    assert store.writes == 0



def test_reviewer_cannot_be_the_implementer():
    store = FakeCASStore()
    with pytest.raises(
        ReviewReplayStateRejected,
        match="reviewer_must_be_independent_of_implementer",
    ):
        verify_and_consume_review_once(
            store=store, snapshot=store.snapshot, attestation=_attestation(),
            public_key_pem=PUBLIC, repository="nonkun12/line-bot",
            cycle_id=CYCLE, commit_sha=COMMIT, expected_nonce=NONCE,
            allowed_reviewers=["trusted-reviewer"],
            public_key_reviewer_id="trusted-reviewer",
            implementer_id="trusted-reviewer", now=NOW,
        )
    assert store.writes == 0
