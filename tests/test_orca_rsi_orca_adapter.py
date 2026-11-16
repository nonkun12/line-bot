import pytest

from scripts.orca_rsi_five_stage import RSI_STAGES, new_cycle, record_stage
from scripts.orca_rsi_orca_adapter import (
    RSIExecutionAdapterRejected,
    to_orca_improvement_candidate,
)


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
        "independent_review_evidence": ["review:run-123"],
        "evaluation": {
            "tests_passed": True,
            "critic_verdict": "pass",
            "baseline_metric": 1.0,
            "candidate_metric": 1.1,
        },
    }
    values.update(overrides)
    return to_orca_improvement_candidate(_cycle(), **values)


def test_adapter_maps_five_rsi_stages_to_six_orca_evidence_stages():
    candidate = _candidate()
    assert set(candidate["evidence"]) == {
        "observed", "diagnosed", "proposed", "tested", "reviewed", "evaluated"
    }
    assert candidate["evidence"]["reviewed"] == ["review:run-123"]
    assert candidate["evidence"]["evaluated"] == ["final evaluation evidence"]


def test_adapter_never_derives_independent_review_from_rsi_cycle():
    with pytest.raises(RSIExecutionAdapterRejected, match="independent_review_evidence_missing"):
        _candidate(independent_review_evidence=[])


def test_adapter_rejects_non_pass_rsi_cycle():
    cycle = new_cycle("not-pass")
    for stage in RSI_STAGES[:-1]:
        cycle = record_stage(cycle, stage=stage, evidence="evidence")
    cycle = record_stage(cycle, stage="select_evolve", evidence="blocked", result="BLOCKED")
    with pytest.raises(RSIExecutionAdapterRejected, match="rsi_cycle_result_not_pass"):
        to_orca_improvement_candidate(
            cycle, cycle_id="a" * 64,
            independent_review_evidence=["review:run-123"], evaluation={},
        )


def test_adapter_keeps_all_execution_switches_false():
    candidate = _candidate()
    assert candidate["execution_authorized"] is False
    assert candidate["auto_apply"] is False
    assert candidate["auto_merge"] is False
    assert candidate["auto_deploy"] is False
