"""Read-only provisioning preflight for the ORCA RSI trust boundary.

This command verifies public-key configuration and an already-provisioned
GitHub state document. It never creates branches, ledgers, keys, or secrets,
and never starts a worker.
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from scripts.orca_github_state_store import GitHubStateStore


_LEDGER_KEYS = (
    "rsi_review_replay",
    "rsi_task_approval_replay",
    "rsi_budget_authorization_replay",
)
_LEDGER_FIELDS = {"used_nonces", "used_attestation_hashes"}


def _json_value(env: Mapping[str, str], name: str, expected: type) -> Any:
    raw = env.get(name, "")
    if not raw:
        raise ValueError(f"{name}_missing")
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise ValueError(f"{name}_invalid_json") from None
    if not isinstance(value, expected):
        raise ValueError(f"{name}_wrong_type")
    return value


def _string_list(env: Mapping[str, str], name: str) -> list[str]:
    value = _json_value(env, name, list)
    if (not value or any(not isinstance(x, str) or not x.strip() for x in value)
            or len(value) != len(set(value))):
        raise ValueError(f"{name}_invalid")
    return value


def _string_map(env: Mapping[str, str], name: str) -> dict[str, str]:
    value = _json_value(env, name, dict)
    if (not value or any(not isinstance(k, str) or not k.strip()
                         or not isinstance(v, str) or not v.strip()
                         for k, v in value.items())):
        raise ValueError(f"{name}_invalid")
    return value


def _public_key(raw: str | bytes, name: str) -> Ed25519PublicKey:
    try:
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        key = serialization.load_pem_public_key(data)
    except (TypeError, ValueError):
        raise ValueError(f"{name}_invalid") from None
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError(f"{name}_not_ed25519")
    return key


def _raw_key(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def _validate_ledger(state: Any, key: str) -> None:
    if not isinstance(state, dict) or key not in state:
        raise ValueError(f"{key}_missing")
    ledger = state[key]
    if not isinstance(ledger, dict) or set(ledger) != _LEDGER_FIELDS:
        raise ValueError(f"{key}_invalid")
    nonces, hashes = ledger["used_nonces"], ledger["used_attestation_hashes"]
    if (not isinstance(nonces, list) or not isinstance(hashes, list)
            or len(nonces) != len(hashes)
            or len(nonces) != len(set(nonces))
            or len(hashes) != len(set(hashes))
            or any(not isinstance(x, str) or not 32 <= len(x) <= 256 for x in nonces)
            or any(not isinstance(x, str) or len(x) != 64
                   or any(c not in "0123456789abcdef" for c in x) for x in hashes)):
        raise ValueError(f"{key}_invalid")


def run_preflight(env: Mapping[str, str] | None = None, state_store: Any = None) -> dict[str, Any]:
    """Return a sanitized report; state_store is used only through read()."""
    values = os.environ if env is None else env
    checks: list[str] = []
    blockers: list[str] = []
    try:
        review_pem = values.get("ORCA_REVIEW_PUBLIC_KEY_PEM", "")
        reviewer_id = values.get("ORCA_REVIEW_PUBLIC_KEY_REVIEWER_ID", "")
        if not review_pem or not reviewer_id:
            raise ValueError("review_public_key_or_identity_missing")
        review_key = _public_key(review_pem, "review_public_key")

        approval_keys = _string_map(values, "ORCA_APPROVAL_KEYRING_JSON")
        approval_signers = _string_map(values, "ORCA_APPROVAL_KEY_SIGNER_MAP_JSON")
        budget_keys = _string_map(values, "ORCA_BUDGET_KEYRING_JSON")
        budget_signers = _string_map(values, "ORCA_BUDGET_KEY_SIGNER_MAP_JSON")
        approvers = _string_list(values, "ORCA_ALLOWED_APPROVERS_JSON")
        budget_issuers = _string_list(values, "ORCA_ALLOWED_BUDGET_ISSUERS_JSON")
        reviewers = _string_list(values, "ORCA_ALLOWED_REVIEWERS_JSON")

        if set(approval_keys) != set(approval_signers):
            raise ValueError("approval_key_signer_map_mismatch")
        if set(budget_keys) != set(budget_signers):
            raise ValueError("budget_key_signer_map_mismatch")
        if any(signer not in approvers for signer in approval_signers.values()):
            raise ValueError("approval_signer_not_allowlisted")
        if any(signer not in budget_issuers for signer in budget_signers.values()):
            raise ValueError("budget_issuer_not_allowlisted")
        if reviewer_id not in reviewers:
            raise ValueError("reviewer_not_allowlisted")

        approval_public = [_public_key(v, "approval_public_key") for v in approval_keys.values()]
        budget_public = [_public_key(v, "budget_public_key") for v in budget_keys.values()]
        all_raw = [_raw_key(review_key)] + [_raw_key(k) for k in approval_public + budget_public]
        if len(all_raw) != len(set(all_raw)):
            raise ValueError("trust_public_keys_not_independent")
        identities = [reviewer_id] + list(approval_signers.values()) + list(budget_signers.values())
        if len(identities) != len(set(identities)):
            raise ValueError("trust_signer_identities_not_independent")
        checks.extend([
            "review_key_valid_and_allowlisted",
            "approval_keys_valid_and_allowlisted",
            "budget_keys_valid_and_allowlisted",
            "trust_domains_use_distinct_keys_and_identities",
        ])

        if state_store is None:
            required = ("GITHUB_TOKEN", "GITHUB_REPOSITORY")
            if any(not values.get(name) for name in required):
                raise ValueError("github_state_store_credentials_missing")
            state_store = GitHubStateStore(
                token=values["GITHUB_TOKEN"],
                repository=values["GITHUB_REPOSITORY"],
                branch=values.get("ORCA_STATE_BRANCH", "orca-state"),
                path=values.get("ORCA_STATE_PATH", "state/queue.json"),
            )
        snapshot = state_store.read()
        state = getattr(snapshot, "state", None)
        if not isinstance(state, dict):
            raise ValueError("orca_state_document_invalid")
        if type(state.get("schema_version")) is not int or state["schema_version"] != 1:
            raise ValueError("orca_state_schema_invalid")
        if type(state.get("revision")) is not int or state["revision"] < 0:
            raise ValueError("orca_state_revision_invalid")
        if state.get("global_hold") is not False:
            raise ValueError("global_hold_active")
        if state.get("emergency_stop") is not False:
            raise ValueError("emergency_stop_active")
        tasks = state.get("tasks")
        if not isinstance(tasks, list):
            raise ValueError("persisted_queue_invalid")
        task_ids: set[str] = set()
        queued = []
        for task in tasks:
            if (not isinstance(task, dict)
                    or not isinstance(task.get("task_id"), str)
                    or not task["task_id"].strip()
                    or not isinstance(task.get("status"), str)
                    or not task["status"].strip()):
                raise ValueError("persisted_queue_entry_invalid")
            if task["task_id"] in task_ids:
                raise ValueError("persisted_queue_duplicate_task_id")
            task_ids.add(task["task_id"])
            if task["status"] == "queued":
                queued.append(task)
        if len(queued) != 1:
            raise ValueError("queued_task_count_not_exactly_one")
        if state.get("active_lease") is not None:
            raise ValueError("worker_lease_already_active")
        for ledger_key in _LEDGER_KEYS:
            _validate_ledger(state, ledger_key)
        checks.append("preprovisioned_state_hold_queue_lease_and_three_replay_ledgers_valid")
    except Exception as exc:
        # Do not expose environment values, tokens, key material, or API responses.
        reason = str(exc).split(":", 1)[0].strip()
        blockers.append(reason or type(exc).__name__)

    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "checks": checks,
        "blockers": blockers,
        "state_written": False,
        "keys_created": False,
        "worker_started": False,
        "production_execution_authorized": False,
    }


def main() -> int:
    report = run_preflight()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
