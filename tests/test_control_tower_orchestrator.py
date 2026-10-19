from __future__ import annotations

from scripts.control_tower_orchestrator import coordinate_outcome


def verified_success(status="PASS"):
    base = "a" * 40
    produced = "b" * 40 if status == "PASS" else base
    return {
        "task_id": "task-a",
        "status": status,
        "rea": {
            "gate": "PASS", "target_sha": base, "critical_count": 0, "blocking_count": 0,
            "execution_authorized": False, "patch_authorized": False,
            "hold_clear_authorized": False, "merge_deploy_authorized": False,
            "scanner_status": "PASS", "finding_count": 0, "findings": [],
        },
        "exit_code": 0,
        "base_sha": base,
        "produced_sha": produced,
        "run_nonce": "c" * 32,
        "recovery_ai": {"recorded": True, "verified": True, "status": status},
        "control_tower": {"recorded": True},
    }


def test_verified_success_requires_all_evidence_and_allows_controlled_continue():
    decision = coordinate_outcome(verified_success())
    assert decision["phase"] == "REPORT"
    assert decision["next_action"] == "REPORT_VERIFIED_SUCCESS"
    assert decision["allow_continue"] is True



def test_rea_evidence_is_required_and_must_match_base_sha():
    result = verified_success()
    result.pop("rea")
    decision = coordinate_outcome(result)
    assert decision["allow_continue"] is False
    assert decision["reason_code"] == "rea_evidence_missing_or_invalid"

    result = verified_success()
    result["rea"]["target_sha"] = "f" * 40
    decision = coordinate_outcome(result)
    assert decision["allow_continue"] is False
    assert decision["reason_code"] == "rea_evidence_missing_or_invalid"


def test_rea_cannot_grant_execution_or_hold_clear_authority():
    result = verified_success()
    result["rea"]["execution_authorized"] = True
    decision = coordinate_outcome(result)
    assert decision["allow_continue"] is False
    assert decision["reason_code"] == "rea_evidence_missing_or_invalid"

def test_rea_high_or_critical_blocking_count_is_rejected():
    result = verified_success()
    result["rea"]["blocking_count"] = 1
    decision = coordinate_outcome(result)
    assert decision["allow_continue"] is False
    assert decision["reason_code"] == "rea_evidence_missing_or_invalid"


def test_no_change_requires_identical_shas():
    result = verified_success("NO_CHANGE")
    result["produced_sha"] = "d" * 40
    decision = coordinate_outcome(result)
    assert decision["allow_continue"] is False
    assert decision["reason_code"] == "no_change_sha_mismatch"


def test_success_without_recovery_record_fails_closed():
    result = verified_success()
    result.pop("recovery_ai")
    decision = coordinate_outcome(result)
    assert decision["allow_continue"] is False
    assert decision["reason_code"] == "recovery_evidence_missing"


def test_success_without_recovery_verification_fails_closed():
    result = verified_success()
    result["recovery_ai"] = {"recorded": True, "verified": False, "status": "PASS"}
    decision = coordinate_outcome(result)
    assert decision["allow_continue"] is False
    assert decision["reason_code"] == "recovery_verification_mismatch"


def test_bool_exit_code_is_not_accepted_as_integer_zero():
    result = verified_success()
    result["exit_code"] = False
    decision = coordinate_outcome(result)
    assert decision["allow_continue"] is False
    assert decision["reason_code"] == "success_exit_code_invalid"


def test_blocked_never_resumes_or_clears_hold():
    decision = coordinate_outcome({
        "task_id": "task-a", "status": "BLOCKED", "exit_code": 80,
        "control_tower": {"recorded": True},
        "recovery_ai": {"recorded": True, "decision": {"action": "REPAIR_ONCE"}},
    })
    assert decision["phase"] == "STOP"
    assert decision["allow_continue"] is False


def test_repair_once_is_a_plan_not_a_claim_of_execution():
    decision = coordinate_outcome({
        "task_id": "task-a", "status": "FAIL", "exit_code": 1,
        "base_sha": "a" * 40,
        "rea": {"gate": "PASS", "target_sha": "a" * 40, "critical_count": 0, "blocking_count": 0,
                "execution_authorized": False, "patch_authorized": False,
                "hold_clear_authorized": False, "merge_deploy_authorized": False},
        "control_tower": {"recorded": True},
        "recovery_ai": {"recorded": True, "decision": {"action": "REPAIR_ONCE"}},
    })
    assert decision["phase"] == "DIAGNOSE"
    assert decision["next_action"] == "PREPARE_BOUNDED_REPAIR_REVIEW"
    assert decision["repair_executed"] is False
    assert decision["allow_continue"] is False


def test_retry_is_a_plan_not_an_execution_or_permission_to_continue():
    decision = coordinate_outcome({
        "task_id": "task-a", "status": "FAIL", "exit_code": 1,
        "base_sha": "a" * 40,
        "rea": {"gate": "PASS", "target_sha": "a" * 40, "critical_count": 0, "blocking_count": 0,
                "execution_authorized": False, "patch_authorized": False,
                "hold_clear_authorized": False, "merge_deploy_authorized": False},
        "control_tower": {"recorded": True},
        "recovery_ai": {"recorded": True, "decision": {"action": "RETRY"}},
    })
    assert decision["phase"] == "RECOVER"
    assert decision["next_action"] == "SCHEDULE_BOUNDED_RETRY"
    assert decision["retry_executed"] is False
    assert decision["allow_continue"] is False


def test_unknown_recovery_action_requires_human_review():
    decision = coordinate_outcome({
        "task_id": "task-a", "status": "FAIL", "exit_code": 1,
        "base_sha": "a" * 40,
        "rea": {"gate": "PASS", "target_sha": "a" * 40, "critical_count": 0, "blocking_count": 0,
                "execution_authorized": False, "patch_authorized": False,
                "hold_clear_authorized": False, "merge_deploy_authorized": False},
        "control_tower": {"recorded": True},
        "recovery_ai": {"recorded": True, "decision": {"action": "RUN_ARBITRARY_COMMAND"}},
    })
    assert decision["phase"] == "STOP"
    assert decision["next_action"] == "HOLD_FOR_REVIEW"


def test_missing_observer_persistence_fails_closed():
    result = verified_success()
    result["control_tower"] = {"recorded": False}
    decision = coordinate_outcome(result)
    assert decision["allow_continue"] is False
    assert decision["phase"] == "STOP"
    assert decision["reason_code"] == "control_tower_observation_missing"
