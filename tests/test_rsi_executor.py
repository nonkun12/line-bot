import sqlite3

import pytest

from core.rsi_executor import (
    EvidenceLedger, ExperimentResult, HumanApproval, IndependentEvaluation,
    Observation, RSIControl, RSIError, RSIExecutor, canonical_digest,
)

H = "a" * 64


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
        executor_id="local-executor",
    )
    return executor, ledger


def sample_plan(executor):
    observations = (
        Observation("obs-1", H, "model", "FAIL", "held-out quality fell", 1),
        Observation("obs-2", "b" * 64, "model", "REGRESSED", "repeat quality regression", 2),
    )
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
    result_digest = canonical_digest({"experiment": plan.experiment_id, "score": 0.9})
    result = executor.execute_approved(
        plan, approval,
        lambda p: ExperimentResult(p.experiment_id, "local-executor", result_digest,
                                   {"quality": 0.9}, "f" * 64),
    )
    evaluation = IndependentEvaluation(
        plan.experiment_id, "independent-evaluator", "IMPROVED",
        "reproduced on frozen holdout", "1" * 64, "valid",
    )
    assert executor.evaluate(result, evaluation).decision == "IMPROVED"
    assert ledger.verify()


def test_executor_cannot_self_evaluate_or_accept_invalid_signature(tmp_path):
    executor, _ = make_executor(tmp_path, execution_enabled=True)
    plan = sample_plan(executor)
    result = ExperimentResult(plan.experiment_id, "local-executor", H, {"quality": 0.8}, "f" * 64)
    self_review = IndependentEvaluation(plan.experiment_id, "local-executor", "IMPROVED", "self", H, "valid")
    with pytest.raises(RSIError, match="cannot evaluate"):
        executor.evaluate(result, self_review)
    forged = IndependentEvaluation(plan.experiment_id, "reviewer", "IMPROVED", "forged", H, "bad")
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
