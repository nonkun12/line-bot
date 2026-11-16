from scripts.orca_rsi_five_stage import (
    RSI_STAGES,
    RSICycleRejected,
    continuation_decision,
    new_cycle,
    record_stage,
)


def _complete_cycle(result="PASS"):
    cycle = new_cycle("test-cycle")
    for stage in RSI_STAGES[:-1]:
        cycle = record_stage(cycle, stage=stage, evidence=f"{stage} evidence")
    return record_stage(
        cycle, stage="select_evolve", evidence="decision evidence", result=result
    )


def _all_gates(**overrides):
    values = {
        "queue_has_pending": True,
        "global_hold": False,
        "emergency_stop": False,
        "budget_verified": True,
        "approval_verified": True,
        "independent_review_pass": True,
        "kill_switch": False,
    }
    values.update(overrides)
    return values


def test_five_rsi_stages_complete_in_order():
    cycle = _complete_cycle()
    assert cycle["completed_stages"] == list(RSI_STAGES)
    assert cycle["result"] == "PASS"
    assert len(cycle["evidence"]) == 5


def test_rsi_rejects_skipped_stage():
    cycle = new_cycle("skip-stage")
    try:
        record_stage(cycle, stage="diagnose", evidence="diagnosis")
    except RSICycleRejected as exc:
        assert str(exc) == "rsi_stage_out_of_order"
    else:
        raise AssertionError("out-of-order stage was accepted")


def test_rsi_rejects_empty_evidence():
    cycle = new_cycle("empty-evidence")
    try:
        record_stage(cycle, stage="evaluate", evidence=" ")
    except RSICycleRejected as exc:
        assert str(exc) == "rsi_stage_evidence_missing_or_invalid"
    else:
        raise AssertionError("empty evidence was accepted")


def test_only_fully_gated_pass_can_continue_one_cycle():
    decision = continuation_decision(_complete_cycle(), **_all_gates())
    assert decision == {
        "status": "PASS",
        "continue": True,
        "next_cycle_limit": 1,
        "reasons": [],
    }


def test_hold_or_missing_budget_blocks_continuation():
    decision = continuation_decision(
        _complete_cycle(),
        **_all_gates(global_hold=True, budget_verified=False),
    )
    assert decision["continue"] is False
    assert decision["next_cycle_limit"] == 0
    assert "global_hold_active" in decision["reasons"]
    assert "budget_evidence_missing_or_invalid" in decision["reasons"]


def test_no_change_does_not_trigger_recursive_execution():
    decision = continuation_decision(
        _complete_cycle(result="NO_CHANGE"), **_all_gates()
    )
    assert decision["continue"] is False
    assert "rsi_result_not_pass" in decision["reasons"]


def test_independent_review_and_approval_are_required():
    decision = continuation_decision(
        _complete_cycle(),
        **_all_gates(approval_verified=False, independent_review_pass=False),
    )
    assert decision["continue"] is False
    assert "task_approval_missing_or_invalid" in decision["reasons"]
    assert "independent_review_not_pass" in decision["reasons"]


def test_truthy_strings_cannot_satisfy_safety_gates():
    decision = continuation_decision(
        _complete_cycle(),
        **_all_gates(global_hold="false", budget_verified="true"),
    )
    assert decision["continue"] is False
    assert "gate_input_not_boolean" in decision["reasons"]
    assert "global_hold_active" in decision["reasons"]
    assert "budget_evidence_missing_or_invalid" in decision["reasons"]


def test_unexpected_extra_evidence_is_rejected():
    cycle = _complete_cycle()
    cycle["evidence"]["unrecognized"] = "not part of the five-stage cycle"
    decision = continuation_decision(cycle, **_all_gates())
    assert decision["continue"] is False
    assert "rsi_evidence_incomplete" in decision["reasons"]
