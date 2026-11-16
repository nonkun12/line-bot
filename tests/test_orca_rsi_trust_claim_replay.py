import copy
from dataclasses import dataclass

import pytest

from scripts.orca_rsi_trust_claim_replay import (
    TrustClaimReplayRejected,
    verify_and_consume_budget_authorization_once,
    verify_and_consume_task_approval_once,
)
from tests.test_orca_rsi_trust_claims import (
    NOW, KEYRING, REPO, TASK, TASK_DIGEST, CYCLE, COMMIT,
    _approval, _budget,
)


@dataclass
class Snapshot:
    ref_sha: str
    state: dict


class FakeCASStore:
    def __init__(self):
        self.snapshot = Snapshot("c" * 40, {
            "schema_version": 1, "revision": 3, "global_hold": True,
            "emergency_stop": False, "tasks": [], "active_lease": None,
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
        keyring=KEYRING, allowed_approvers=["human-approver"],
        repository=REPO, task_id=TASK, task_digest=TASK_DIGEST,
        cycle_id=CYCLE, commit_sha=COMMIT, now=NOW,
        implementer_id="worker-author",
    )


def _consume_budget(store):
    evidence = b"trusted collector evidence v1"
    return verify_and_consume_budget_authorization_once(
        store=store, snapshot=store.snapshot, claim=_budget(evidence),
        keyring=KEYRING, allowed_issuers=["budget-authority"],
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
    assert "rsi_budget_authorization_replay" not in store.snapshot.state
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
            keyring=KEYRING, allowed_approvers=["human-approver"],
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
