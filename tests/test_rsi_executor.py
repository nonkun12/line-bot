import sqlite3
from dataclasses import replace

import pytest

from core.rsi_executor import (
    EvidenceLedger, ExperimentResult, HumanApproval, IndependentEvaluation,
    Observation, RSIControl, RSIError, RSIExecutor, canonical_digest,
)

H = "a" * 64


class FreeLocalRunner:
    is_local = True
    paid_fallback_enabled = False

    def __call__(self, plan):
        result_digest = canonical_digest({"experiment": plan.experiment_id, "score": 0.9})
        return ExperimentResult(plan.experiment_id, "local-executor", result_digest,
                                {"quality": 0.9}, "f" * 64)


def make_executor(tmp_path, *, execution_enabled=False, hold=False, budget_known=True, paid=False):
    control = RSIControl(
        global_hold=hold,
        execution_enabled=execution_enabled,
        free_only=True,
        budget_known=budget_known,
        budget_remaining_units=10,
        paid_fallback_enabled=paid,
    )
    ledger = EvidenceLedger(tmp_path / "rsi.sqlite")
    executor = RSIExecutor(
        ledger,
        control_provider=lambda: control,
        verify_approval=lambda approval: approval.signature == "valid",
        verify_evaluation=lambda evaluation: evaluation.signature == "valid",
        verify_evidence_signature=lambda digest, signature: signature == "sig:" + digest,
        executor_id="local-executor",
    )
    return executor, ledger


def sample_plan(executor):
    observations = (
        Observation("obs-1", H, "model", "FAIL", "held-out quality fell", 1),
        Observation("obs-2", "b" * 64, "model", "REGRESSED", "repeat quality regression", 2),
    )
    observations = seed_observations(executor.ledger, observations)
    diagnoses = executor.observe(observations)
    hypotheses = executor.hypothesize(diagnoses)
    plans = executor.plan(
        hypotheses, baseline_digest="c" * 64, candidate_digest="d" * 64,
        protocol_digest="e" * 64, expected_cost_units=2,
    )
    return executor.select_next(plans)


def test_rsi_pipeline_generates_diagnosis_hypothesis_and_selects_plan(tmp_path):
    executor, ledger = make_executor(tmp_path)
    plan = sample_plan(executor)
    assert plan.capability == "model"
    assert len(plan.plan_digest) == 64
    assert ledger.verify()


def test_hold_free_budget_and_paid_fallback_fail_closed(tmp_path):
    executor, _ = make_executor(tmp_path, hold=True)
    with pytest.raises(RSIError, match="Global HOLD"):
        executor.observe((Observation("obs", H, "model", "FAIL", "failure", 1),))

    executor, _ = make_executor(tmp_path, budget_known=False)
    with pytest.raises(RSIError, match="budget unknown"):
        executor.observe((Observation("obs", H, "model", "FAIL", "failure", 1),))

    executor, _ = make_executor(tmp_path, paid=True)
    with pytest.raises(RSIError, match="FREE-only"):
        executor.observe((Observation("obs", H, "model", "FAIL", "failure", 1),))


def test_execution_requires_exact_human_approval_and_enabled_control(tmp_path):
    executor, _ = make_executor(tmp_path, execution_enabled=False)
    plan = sample_plan(executor)
    approval = HumanApproval("human-1", plan.plan_digest, "nonce-1", "valid")
    called = []
    with pytest.raises(RSIError, match="execution is disabled"):
        executor.execute_approved(plan, approval, lambda p: called.append(p))
    assert not called


def test_approved_local_execution_and_independent_evaluation(tmp_path):
    executor, ledger = make_executor(tmp_path, execution_enabled=True)
    plan = sample_plan(executor)
    approval = HumanApproval("human-1", plan.plan_digest, "nonce-2", "valid")
    result = executor.execute_approved(plan, approval, FreeLocalRunner())
    evaluation = IndependentEvaluation(
        plan.experiment_id, result.result_digest, "independent-evaluator", "IMPROVED",
        "reproduced on frozen holdout", "1" * 64, "valid",
    )
    assert executor.evaluate(result, evaluation).decision == "IMPROVED"
    with pytest.raises(RSIError, match="duplicate evidence"):
        executor.execute_approved(plan, approval, FreeLocalRunner())
    assert ledger.verify()


def test_executor_cannot_self_evaluate_or_accept_invalid_signature(tmp_path):
    executor, _ = make_executor(tmp_path, execution_enabled=True)
    plan = sample_plan(executor)
    result = ExperimentResult(plan.experiment_id, "local-executor", H, {"quality": 0.8}, "f" * 64)
    self_review = IndependentEvaluation(plan.experiment_id, result.result_digest, "local-executor", "IMPROVED", "self", H, "valid")
    with pytest.raises(RSIError, match="cannot evaluate"):
        executor.evaluate(result, self_review)
    forged = IndependentEvaluation(plan.experiment_id, result.result_digest, "reviewer", "IMPROVED", "forged", H, "bad")
    with pytest.raises(RSIError, match="signature"):
        executor.evaluate(result, forged)


def test_ledger_is_append_only_and_detects_tampering(tmp_path):
    ledger = EvidenceLedger(tmp_path / "ledger.sqlite")
    ledger.append("event-1", "observation", {"evidence": H})
    assert ledger.verify()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with sqlite3.connect(ledger.path) as db:
            db.execute("UPDATE rsi_evidence SET payload='{}' WHERE event_id='event-1'")
    with pytest.raises(RSIError, match="duplicate evidence"):
        ledger.append("event-1", "observation", {"evidence": H})
    assert ledger.verify()


def test_duplicate_observation_and_bad_digest_are_rejected(tmp_path):
    executor, _ = make_executor(tmp_path)
    duplicate = Observation("same", H, "model", "FAIL", "x", 1)
    with pytest.raises(RSIError, match="duplicate observation"):
        executor.observe((duplicate, duplicate))
    bad = Observation("bad", "not-a-digest", "model", "FAIL", "x", 1)
    with pytest.raises(RSIError, match="SHA-256"):
        executor.observe((bad,))



def test_plan_digest_prevents_priority_tampering(tmp_path):
    executor, _ = make_executor(tmp_path)
    plan = sample_plan(executor)
    altered = replace(plan, information_value=1.0)
    with pytest.raises(RSIError, match="digest mismatch"):
        executor.select_next((altered,))



def test_planning_rejects_experiment_cost_above_known_free_budget(tmp_path):
    ledger = EvidenceLedger(tmp_path / "budget.sqlite")
    executor = RSIExecutor(
        ledger,
        control_provider=lambda: RSIControl(
            False, False, True, True, 1, False
        ),
        verify_approval=lambda _: False,
        verify_evaluation=lambda _: False,
        executor_id="rsi-planner",
    )
    observations = (
        Observation("budget-obs-1", H, "model", "FAIL", "quality fell", 1),
        Observation("budget-obs-2", "b" * 64, "model", "REGRESSED", "repeat regression", 2),
    )
    hypotheses = executor.hypothesize(executor.observe(observations))
    with pytest.raises(RSIError, match="budget unknown or insufficient"):
        executor.plan(
            hypotheses,
            baseline_digest="c" * 64,
            candidate_digest="d" * 64,
            protocol_digest="e" * 64,
            expected_cost_units=2,
        )


def test_control_rejects_boolean_budget_and_non_boolean_flags(tmp_path):
    ledger = EvidenceLedger(tmp_path / "invalid-control.sqlite")
    invalid_states = (
        RSIControl(False, False, True, True, True, False),
        RSIControl(0, False, True, True, 5, False),
    )
    for invalid in invalid_states:
        executor = RSIExecutor(
            ledger,
            control_provider=lambda invalid=invalid: invalid,
            verify_approval=lambda _: False,
            verify_evaluation=lambda _: False,
            executor_id="rsi-planner",
        )
        with pytest.raises(RSIError, match="invalid"):
            executor.observe((
                Observation("invalid-control-" + str(invalid_states.index(invalid)),
                            H, "model", "PASS", "baseline", 1),
            ))



def seed_observations(ledger, observations):
    from dataclasses import replace
    seeded = []
    for item in observations:
        event_id = "source-evidence:" + item.observation_id
        digest = ledger.append_observation_evidence(
            event_id, observation=item,
            experiment_id="source-" + item.observation_id,
            candidate_digest="c" * 64,
            protocol_digest="d" * 64,
            result_digest="e" * 64,
            producer_id="test-producer",
            sign_digest=lambda value: "sig:" + value,
        )
        seeded.append(replace(item, evidence_digest=digest, evidence_event_id=event_id, experiment_id="source-" + item.observation_id, candidate_digest="c" * 64, protocol_digest="d" * 64, result_digest="e" * 64))
    return tuple(seeded)



def test_observation_rejects_missing_source_evidence_and_invalid_producer_signature(tmp_path):
    executor, ledger = make_executor(tmp_path)
    raw = Observation("missing-source", H, "model", "FAIL", "quality fell", 1, "absent-source-event", "experiment-missing", "c" * 64, "d" * 64, "e" * 64)
    with pytest.raises(RSIError, match="missing"):
        executor.observe((raw,))

    raw = Observation("bad-signature", H, "model", "FAIL", "quality fell", 1, "", "experiment-1", "c" * 64, "d" * 64, "e" * 64)
    event_id = "source-evidence:bad-signature"
    digest = ledger.append_observation_evidence(
        event_id, observation=raw, experiment_id="experiment-1",
        candidate_digest="c" * 64, protocol_digest="d" * 64,
        result_digest="e" * 64, producer_id="untrusted-producer",
        sign_digest=lambda _: "forged",
    )
    forged = replace(raw, evidence_digest=digest, evidence_event_id=event_id)
    with pytest.raises(RSIError, match="signature verification failed"):
        executor.observe((forged,))


def test_observation_rejects_source_payload_mismatch_and_forbidden_event_type(tmp_path):
    executor, ledger = make_executor(tmp_path)
    raw = Observation("payload-mismatch", H, "model", "FAIL", "original detail", 1, "", "experiment-2", "c" * 64, "d" * 64, "e" * 64)
    event_id = "source-evidence:payload-mismatch"
    digest = ledger.append_observation_evidence(
        event_id, observation=raw, experiment_id="experiment-2",
        candidate_digest="c" * 64, protocol_digest="d" * 64,
        result_digest="e" * 64, producer_id="test-producer",
        sign_digest=lambda value: "sig:" + value,
    )
    altered = replace(raw, evidence_digest=digest, evidence_event_id=event_id, detail="altered detail")
    with pytest.raises(RSIError, match="does not match"):
        executor.observe((altered,))
    wrong_binding = replace(
        raw, evidence_digest=digest, evidence_event_id=event_id,
        experiment_id="different-experiment",
    )
    with pytest.raises(RSIError, match="experiment binding mismatch"):
        executor.observe((wrong_binding,))

    forbidden_id = "forbidden-source"
    forbidden_digest = ledger.append(forbidden_id, "observation", {"evidence": H})
    forbidden = Observation(
        "forbidden-observation", forbidden_digest, "model", "FAIL",
        "detail", 2, forbidden_id, "experiment-forbidden", "c" * 64, "d" * 64, "e" * 64,
    )
    with pytest.raises(RSIError, match="event type is not allowed"):
        executor.observe((forbidden,))


def test_observation_rejects_tampered_hash_chain_before_acceptance(tmp_path):
    executor, ledger = make_executor(tmp_path)
    raw = Observation("tampered-source", H, "model", "FAIL", "quality fell", 1, "", "experiment-3", "c" * 64, "d" * 64, "e" * 64)
    event_id = "source-evidence:tampered-source"
    digest = ledger.append_observation_evidence(
        event_id, observation=raw, experiment_id="experiment-3",
        candidate_digest="c" * 64, protocol_digest="d" * 64,
        result_digest="e" * 64, producer_id="test-producer",
        sign_digest=lambda value: "sig:" + value,
    )
    with sqlite3.connect(ledger.path) as db:
        db.execute("DROP TRIGGER rsi_evidence_no_update")
        db.execute("UPDATE rsi_evidence SET payload='{}' WHERE event_id=?", (event_id,))
    item = replace(raw, evidence_digest=digest, evidence_event_id=event_id)
    with pytest.raises(RSIError, match="integrity verification failed"):
        executor.observe((item,))
