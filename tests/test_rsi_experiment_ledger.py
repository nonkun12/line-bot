"""Tests for the append-only RSI experiment evidence ledger."""
from __future__ import annotations

import json

import pytest

from scripts.rsi_experiment_ledger import append_ledger_entry, verify_ledger


def test_append_creates_hash_chained_entries(tmp_path):
    path = tmp_path / "rsi" / "experiments.jsonl"

    first = append_ledger_entry(path, {"experiment_id": "rsi-1", "status": "PASS"})
    second = append_ledger_entry(path, {"experiment_id": "rsi-2", "status": "FAIL"})

    entries = verify_ledger(path)
    assert len(entries) == 2
    assert entries[0]["sequence"] == 1
    assert entries[1]["sequence"] == 2
    assert entries[1]["previous_sha256"] == first
    assert entries[1]["entry_sha256"] == second


def test_missing_ledger_is_empty_and_read_only(tmp_path):
    path = tmp_path / "missing.jsonl"

    assert verify_ledger(path) == []
    assert not path.exists()


def test_tampered_payload_is_detected(tmp_path):
    path = tmp_path / "ledger.jsonl"
    append_ledger_entry(path, {"experiment_id": "rsi-1", "status": "PASS"})
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["status"] = "FAIL"
    path.write_text(json.dumps(envelope) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ledger_digest_mismatch"):
        verify_ledger(path)


def test_broken_chain_is_detected(tmp_path):
    path = tmp_path / "ledger.jsonl"
    append_ledger_entry(path, {"experiment_id": "rsi-1"})
    append_ledger_entry(path, {"experiment_id": "rsi-2"})
    lines = path.read_text(encoding="utf-8").splitlines()
    second = json.loads(lines[1])
    second["previous_sha256"] = "f" * 64
    lines[1] = json.dumps(second)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ledger_chain_invalid"):
        verify_ledger(path)


def test_invalid_payload_does_not_create_or_mutate_ledger(tmp_path):
    path = tmp_path / "ledger.jsonl"

    with pytest.raises(ValueError):
        append_ledger_entry(path, {"bad_number": float("nan")})

    assert not path.exists()



@pytest.mark.parametrize("payload", [
    {"api_key": "secret-value"},
    {"nested": {"github_token": "secret-value"}},
    {"items": [{"client_secret": "secret-value"}]},
])
def test_credential_fields_are_rejected_before_ledger_mutation(tmp_path, payload):
    path = tmp_path / "ledger.jsonl"

    with pytest.raises(ValueError, match="ledger_sensitive_field_rejected"):
        append_ledger_entry(path, payload)

    assert not path.exists()
