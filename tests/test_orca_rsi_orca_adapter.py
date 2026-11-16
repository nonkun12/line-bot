from datetime import datetime, timezone

import pytest

from scripts.orca_rsi_five_stage import RSI_STAGES, new_cycle, record_stage
from scripts.orca_rsi_orca_adapter import (
    RSIExecutionAdapterRejected,
    to_orca_improvement_candidate,
)
from tests.test_orca_rsi_review_attestation import KEY, NOW, _attestation


def _cycle():
    value = new_cycle("adapter-test")
    for stage in RSI_STAGES[:-1]:
        value = record_stage(value, stage=stage, evidence=f"{stage} evidence")
    return record_stage(
        value, stage="select_evolve", evidence="final evaluation evidence",
        result="PASS",
    )


def _candidate(**overrides):
    values = {
        "cycle_id": "a" * 64,
        "repository": "nonkun12/line-bot",
        "commit_sha": "b" * 40,
        "review_attestation": _attestation(),
        "review_signing_key": KEY,
        "allowed_reviewers": ["trusted-reviewer"],
        "now": NOW,
        "evaluation": {
            "tests_passed": True,
            "critic_verdict": "pass",
            "baseline_metric": 1.0,
            "candidate_metric": 1.1,
        },
    }
    values.update(overrides)
    return to_orca_improvement_candidate(_cycle(), **values)


def test_adapter_maps_rsi_stages_only_with_verified_external_review():
    candidate = _candidate()
    assert set(candidate["evidence"]) == {
        "observed", "diagnosed", "proposed", "tested", "reviewed", "evaluated"
    }
    assert candidate["evidence"]["reviewed"] == ["actions://review/123"]


def test_adapter_rejects_unsigned_or_tampered_review():
    forged = _attestation()
    forged["evidence_refs"] = ["actions://forged"]
    with pytest.raises(RSIExecutionAdapterRejected, match="review_signature_invalid"):
        _candidate(review_attestation=forged)


def test_adapter_rejects_review_bound_to_another_commit():
    with pytest.raises(RSIExecutionAdapterRejected, match="review_commit_mismatch"):
        _candidate(review_attestation=_attestation(commit_sha="c" * 40))


def test_adapter_keeps_all_execution_switches_false():
    candidate = _candidate()
    assert candidate["execution_authorized"] is False
    assert candidate["auto_apply"] is False
    assert candidate["auto_merge"] is False
    assert candidate["auto_deploy"] is False
