import json
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.orca_rsi_provisioning_preflight import run_preflight


def _pem(seed):
    key = Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


class ReadOnlyStateStore:
    def __init__(self, state):
        self.state = state
        self.reads = 0
        self.writes = 0

    def read(self):
        self.reads += 1
        return SimpleNamespace(state=self.state)

    def write(self, **kwargs):
        self.writes += 1
        raise AssertionError("preflight must never write state")


def _env():
    return {
        "ORCA_REVIEW_PUBLIC_KEY_PEM": _pem(1),
        "ORCA_REVIEW_PUBLIC_KEY_REVIEWER_ID": "reviewer-one",
        "ORCA_ALLOWED_REVIEWERS_JSON": json.dumps(["reviewer-one"]),
        "ORCA_APPROVAL_KEYRING_JSON": json.dumps({"approval-key": _pem(2)}),
        "ORCA_APPROVAL_KEY_SIGNER_MAP_JSON": json.dumps({"approval-key": "approver-one"}),
        "ORCA_ALLOWED_APPROVERS_JSON": json.dumps(["approver-one"]),
        "ORCA_BUDGET_KEYRING_JSON": json.dumps({"budget-key": _pem(3)}),
        "ORCA_BUDGET_KEY_SIGNER_MAP_JSON": json.dumps({"budget-key": "budget-one"}),
        "ORCA_ALLOWED_BUDGET_ISSUERS_JSON": json.dumps(["budget-one"]),
    }


def _state():
    empty = {"used_nonces": [], "used_attestation_hashes": []}
    return {
        "schema_version": 1,
        "revision": 7,
        "global_hold": False,
        "emergency_stop": False,
        "tasks": [{"task_id": "preflight-task", "status": "queued"}],
        "active_lease": None,
        "rsi_review_replay": dict(empty),
        "rsi_task_approval_replay": dict(empty),
        "rsi_budget_authorization_replay": dict(empty),
    }


def test_preflight_passes_with_distinct_trust_domains_and_preprovisioned_ledgers():
    store = ReadOnlyStateStore(_state())
    report = run_preflight(_env(), store)
    assert report["status"] == "PASS"
    assert report["worker_started"] is False
    assert report["production_execution_authorized"] is False
    assert store.reads == 1
    assert store.writes == 0


def test_preflight_blocks_global_hold_without_writing_state():
    state = _state()
    state["global_hold"] = True
    store = ReadOnlyStateStore(state)
    report = run_preflight(_env(), store)
    assert report["status"] == "BLOCKED"
    assert "global_hold_active" in report["blockers"]
    assert store.writes == 0


def test_preflight_blocks_when_queue_is_empty():
    state = _state()
    state["tasks"] = []
    store = ReadOnlyStateStore(state)
    report = run_preflight(_env(), store)
    assert report["status"] == "BLOCKED"
    assert "queued_task_count_not_exactly_one" in report["blockers"]
    assert store.writes == 0


def test_preflight_blocks_when_state_ledger_missing_without_initializing():
    state = _state()
    del state["rsi_budget_authorization_replay"]
    store = ReadOnlyStateStore(state)
    report = run_preflight(_env(), store)
    assert report["status"] == "BLOCKED"
    assert "rsi_budget_authorization_replay_missing" in report["blockers"]
    assert "rsi_budget_authorization_replay" not in state
    assert store.writes == 0


def test_preflight_blocks_when_public_keys_are_shared():
    env = _env()
    env["ORCA_APPROVAL_KEYRING_JSON"] = json.dumps({"approval-key": env["ORCA_REVIEW_PUBLIC_KEY_PEM"]})
    report = run_preflight(env, ReadOnlyStateStore(_state()))
    assert report["status"] == "BLOCKED"
    assert "trust_public_keys_not_independent" in report["blockers"]


def test_preflight_blocks_when_signer_identity_is_reused_across_domains():
    env = _env()
    env["ORCA_BUDGET_KEY_SIGNER_MAP_JSON"] = json.dumps({"budget-key": "approver-one"})
    env["ORCA_ALLOWED_BUDGET_ISSUERS_JSON"] = json.dumps(["approver-one"])
    report = run_preflight(env, ReadOnlyStateStore(_state()))
    assert report["status"] == "BLOCKED"
    assert "trust_signer_identities_not_independent" in report["blockers"]


def test_preflight_blocks_missing_configuration_without_reading_state():
    store = ReadOnlyStateStore(_state())
    report = run_preflight({}, store)
    assert report["status"] == "BLOCKED"
    assert store.reads == 0
    assert store.writes == 0
