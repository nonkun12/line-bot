import hashlib

from core.ai_factory_stage311_315_sampling_evaluator_controls import (
    stage311_check_inclusion_probabilities,
    stage312_check_evaluator_assignment_balance,
    stage313_check_configuration_scope,
    stage314_check_paired_attrition,
    stage315_integrate_sampling_evaluator_controls,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def sampling():
    return stage311_check_inclusion_probabilities(
        sampling_design="stratified-paired-v1",
        baseline_probabilities={"t1": 0.5, "t2": 0.7},
        candidate_probabilities={"t1": 0.5, "t2": 0.7},
    )


def evaluators():
    return stage312_check_evaluator_assignment_balance(
        evaluator_tasks={"eval-a": ["t1", "t2"], "eval-b": ["t3", "t4"]},
        maximum_task_share=0.6,
    )


def configuration():
    return stage313_check_configuration_scope(
        baseline_invariant_digest=digest("invariant"),
        candidate_invariant_digest=digest("invariant"),
        changed_fields=["candidate.model"],
        allowed_change_fields=["candidate.model"],
    )


def attrition():
    return stage314_check_paired_attrition(
        task_presence={f"t{i}": {"baseline": True, "candidate": True} for i in range(10)}
    )


def test_311_inclusion_probabilities_are_paired_and_bounded():
    assert sampling()["status"] == "SAMPLING_PROBABILITIES_VALID"
    assert stage311_check_inclusion_probabilities(
        sampling_design="design", baseline_probabilities={"t1": 0.0},
        candidate_probabilities={"t1": 0.5},
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage311_check_inclusion_probabilities(
        sampling_design="design", baseline_probabilities={"t1": 0.5},
        candidate_probabilities={"t2": 0.5},
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_312_evaluator_assignment_balance_and_malformed_inputs():
    assert evaluators()["status"] == "EVALUATOR_ASSIGNMENT_BALANCED"
    assert stage312_check_evaluator_assignment_balance(
        evaluator_tasks={"eval-a": ["1", "2", "3", "4"], "eval-b": ["5"]},
        maximum_task_share=0.6,
    )["status"] == "EVALUATOR_ASSIGNMENT_IMBALANCED"
    assert stage312_check_evaluator_assignment_balance(
        evaluator_tasks={"eval-a": ["1"], "eval-b": ["1"]}
    )["status"] == "EVALUATOR_ASSIGNMENT_BALANCED"


def test_313_configuration_scope_and_drift():
    assert configuration()["status"] == "CONFIGURATION_SCOPE_VALID"
    assert stage313_check_configuration_scope(
        baseline_invariant_digest=digest("a"), candidate_invariant_digest=digest("b"),
        changed_fields=[], allowed_change_fields=[],
    )["status"] == "INVARIANT_CONFIGURATION_DRIFT"
    assert stage313_check_configuration_scope(
        baseline_invariant_digest=digest("a"), candidate_invariant_digest=digest("a"),
        changed_fields=["temperature"], allowed_change_fields=["candidate.model"],
    )["status"] == "UNSCOPED_CONFIGURATION_CHANGE"


def test_314_paired_attrition_gap():
    assert attrition()["status"] == "PAIRED_ATTRITION_PARITY_PASSED"
    presence = {f"t{i}": {"baseline": True, "candidate": i < 8} for i in range(10)}
    assert stage314_check_paired_attrition(
        task_presence=presence, maximum_attrition_gap=0.1
    )["status"] == "PAIRED_ATTRITION_GAP_FAILED"
    assert stage314_check_paired_attrition(
        task_presence={"t1": {"baseline": True, "candidate": True}}
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_315_integrates_sealed_gates_and_fails_closed():
    result = stage315_integrate_sampling_evaluator_controls(
        sampling_result=sampling(), evaluator_result=evaluators(),
        configuration_result=configuration(), attrition_result=attrition(),
    )
    assert result["status"] == "SAMPLING_EVALUATOR_CONTROLS_PASSED"
    assert result["asi_demonstrated"] is False
    tampered = dict(sampling())
    tampered["sampling_design"] = "forged"
    assert stage315_integrate_sampling_evaluator_controls(
        sampling_result=tampered, evaluator_result=evaluators(),
        configuration_result=configuration(), attrition_result=attrition(),
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage315_integrate_sampling_evaluator_controls(
        sampling_result=sampling(), evaluator_result=evaluators(),
        configuration_result=configuration(), attrition_result=attrition(), held=True,
    )["status"] == "INSUFFICIENT_EVIDENCE"
