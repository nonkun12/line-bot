"""Tests for the approved local-only RSI prompt comparison runner."""
from __future__ import annotations

import hashlib
import json

from core.local_model_client import LocalModelClient
from core.rsi_local_experiment import run_local_prompt_comparison
from scripts.rsi_experiment_ledger import verify_ledger


class FakeClient(LocalModelClient):
    def __init__(self, responses):
        super().__init__("http://127.0.0.1:11434", "test-local", "ollama")
        self.responses = iter(responses)
        self.calls = []
        self.chat.completions.create = self._create

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Response",
            (),
            {"choices": [type("Choice", (), {"message": type("Message", (), {"content": next(self.responses)})()})()]},
        )()


def _args(client=None, ledger_path=None):
    dataset = [
        {"sample_id": "a", "input": "first", "expected": "one"},
        {"sample_id": "b", "input": "second", "expected": "two"},
    ]
    safety_snapshot = {
        "stop_state": "INACTIVE",
        "global_hold_state": "CLEAR",
    }
    safety_snapshot["snapshot_sha256"] = hashlib.sha256(
        json.dumps(safety_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return {
        "client": client or FakeClient(["one", "wrong", "one", "two"]),
        "experiment_id": "rsi-local-prompt-001",
        "dataset": dataset,
        "held_out_expected_sha256": hashlib.sha256(
            json.dumps(dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest(),
        "held_out_locked": True,
        "baseline_candidate_id": "prompt-v1",
        "baseline_system_prompt": "Answer with the expected vocabulary item.",
        "challenger_candidate_id": "prompt-v2",
        "challenger_system_prompt": "Answer with only the correct vocabulary item.",
        "evaluator_id": "rsi.exact_match.v1",
        "evaluator_version": "1",
        "minimum_delta": 0.5,
        "safety_snapshot": safety_snapshot,
        "execution_approved": True,
        "ledger_path": ledger_path,
    }


def test_runner_generates_both_candidates_locally_and_evaluates_outputs(tmp_path):
    client = FakeClient(["one", "wrong", "one", "two"])
    args = _args(client, tmp_path / "rsi-ledger.jsonl")

    result = run_local_prompt_comparison(**args)

    assert result["result"]["status"] == "PASS"
    assert result["baseline_correct"] == 1
    assert result["challenger_correct"] == 2
    assert len(client.calls) == 4
    assert all(call["temperature"] == 0.0 for call in client.calls)
    assert all(call["max_completion_tokens"] == 256 for call in client.calls)
    assert result["result"]["execution_authorized"] is False
    entries = verify_ledger(tmp_path / "rsi-ledger.jsonl")
    assert len(entries) == 1
    assert result["ledger_entry_sha256"] == entries[0]["entry_sha256"]


def test_runner_blocks_without_explicit_approval_before_model_call(tmp_path):
    client = FakeClient([])
    args = _args(client)
    args["execution_approved"] = False

    result = run_local_prompt_comparison(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "experiment_approval_missing"
    assert client.calls == []


def test_runner_blocks_when_stop_is_active_before_model_call(tmp_path):
    client = FakeClient([])
    args = _args(client)
    args["safety_snapshot"]["stop_state"] = "ACTIVE"

    result = run_local_prompt_comparison(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "stop_active_or_unverified"
    assert client.calls == []


def test_runner_blocks_when_hold_is_not_clear_before_model_call(tmp_path):
    client = FakeClient([])
    args = _args(client)
    args["safety_snapshot"]["global_hold_state"] = "UNKNOWN"

    result = run_local_prompt_comparison(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "global_hold_active_or_unverified"
    assert client.calls == []


def test_runner_blocks_when_held_out_manifest_digest_mismatches(tmp_path):
    args = _args(ledger_path=tmp_path / "rsi-ledger.jsonl")
    args["held_out_expected_sha256"] = "f" * 64

    result = run_local_prompt_comparison(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "held_out_manifest_digest_mismatch"
    assert args["client"].calls == []


def test_runner_blocks_invalid_client_without_execution(tmp_path):
    args = _args()
    args["client"] = object()

    result = run_local_prompt_comparison(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "local_model_client_invalid"



def test_runner_binds_full_input_manifest_digest_into_evidence(tmp_path):
    args = _args()
    expected_digest = args["held_out_expected_sha256"]

    result = run_local_prompt_comparison(**args)

    assert result["record"]["held_out"]["dataset_sha256"] == expected_digest
    assert result["record"]["safety"]["snapshot_sha256"] == args["safety_snapshot"]["snapshot_sha256"]


def test_runner_blocks_without_safety_snapshot_digest_before_model_call(tmp_path):
    client = FakeClient([])
    args = _args(client)
    args["safety_snapshot"].pop("snapshot_sha256")

    result = run_local_prompt_comparison(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "safety_snapshot_digest_missing_or_invalid"
    assert client.calls == []

def test_runner_blocks_when_safety_snapshot_digest_is_tampered(tmp_path):
    args = _args()
    args["safety_snapshot"]["snapshot_sha256"] = "f" * 64

    result = run_local_prompt_comparison(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "safety_snapshot_digest_mismatch"
    assert args["client"].calls == []
