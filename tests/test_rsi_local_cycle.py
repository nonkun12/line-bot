from __future__ import annotations

import pytest

from core.rsi_executor import (
    EvidenceLedger, ExperimentPlan, ExperimentResult, HumanApproval,
    IndependentEvaluation, RSIControl, RSIError, RSIExecutor, canonical_digest,
)
from core.rsi_local_cycle import run_local_rsi_cycle


class FakeLocalRunner:
    is_local = True
    paid_fallback_enabled = False

    def __init__(self):
        self.calls = 0

    def __call__(self, plan):
        self.calls += 1
        return ExperimentResult(
            plan.experiment_id, "local-runner", "c" * 64,
            {"quality": 0.75, "case_count": 4.0}, "d" * 64,
        )


class FakeIndependentEvaluator:
    evaluator_id = "independent-evaluator"

    def __init__(self, decision):
        self.decision = decision
        self.calls = 0

    def evaluate(self, plan, result):
        self.calls += 1
        return IndependentEvaluation(
            plan.experiment_id, result.result_digest, self.evaluator_id,
            self.decision, "independently recomputed benchmark result",
            "e" * 64, "evaluation-signature",
        )


def make_plan():
    baseline, candidate, protocol = "a" * 64, "b" * 64, "f" * 64
    fields = {
        "hypothesis": "hypothesis-1", "capability": "model",
        "baseline": baseline, "candidate": candidate, "protocol": protocol,
        "cost": 4, "risk": 0.1, "information_value": 0.5,
    }
    digest = canonical_digest(fields)
    return ExperimentPlan(
        digest[:32], "hypothesis-1", "model", baseline, candidate, protocol,
        4, 0.1, 0.5, digest,
    )


def make_executor(tmp_path, *, hold=False):
    ledger = EvidenceLedger(tmp_path / "local-cycle.sqlite")
    executor = RSIExecutor(
        ledger,
        control_provider=lambda: RSIControl(
            hold, True, True, True, 20, False
        ),
        verify_approval=lambda approval: approval.signature == "human-signed",
        verify_evaluation=lambda evaluation: evaluation.signature == "evaluation-signature",
        verify_evidence_signature=lambda producer, digest, signature: (
            producer == "independent-evaluator" and signature == "attested:" + digest
        ),
        executor_id="local-runner",
    )
    return executor, ledger


def make_approval(plan):
    return HumanApproval(
        "human-operator", plan.plan_digest, "approval-nonce", "human-signed"
    )


def test_local_cycle_records_signed_evaluation_and_regression_feedback(tmp_path):
    executor, ledger = make_executor(tmp_path)
    runner = FakeLocalRunner()
    evaluator = FakeIndependentEvaluator("REGRESSED")
    result = run_local_rsi_cycle(
        plan=make_plan(), approval=make_approval(make_plan()), runner=runner,
        evaluator=evaluator, executor=executor,
        sign_observation_digest=lambda digest: "attested:" + digest,
        created_at=123,
    )
    assert runner.calls == evaluator.calls == 1
    assert result["decision"] == "REGRESSED"
    assert result["observation_outcome"] == "REGRESSED"
    assert result["evaluation_recorded"] is True
    assert result["observation_recorded"] is True
    assert len(result["diagnosis_ids"]) == 1
    assert len(result["hypothesis_ids"]) == 1
    assert result["selected_plan"]["plan_digest"]
    assert result["execution_started"] is True
    assert result["authority"]["patch_authorized"] is False
    assert ledger.verify()


@pytest.mark.parametrize(
    ("decision", "outcome", "has_diagnosis"),
    [
        ("IMPROVED", "PASS", False),
        ("NO_CHANGE", "INCONCLUSIVE", False),
        ("INCONCLUSIVE", "INCONCLUSIVE", False),
    ],
)
def test_non_regression_decisions_are_not_mislabeled_as_failures(
    tmp_path, decision, outcome, has_diagnosis
):
    executor, ledger = make_executor(tmp_path)
    plan = make_plan()
    result = run_local_rsi_cycle(
        plan=plan, approval=make_approval(plan), runner=FakeLocalRunner(),
        evaluator=FakeIndependentEvaluator(decision), executor=executor,
        sign_observation_digest=lambda digest: "attested:" + digest,
        created_at=123,
    )
    assert result["observation_outcome"] == outcome
    assert bool(result["diagnosis_ids"]) is has_diagnosis
    assert ledger.verify()


def test_global_hold_blocks_before_local_runner_is_invoked(tmp_path):
    executor, ledger = make_executor(tmp_path, hold=True)
    runner = FakeLocalRunner()
    plan = make_plan()
    with pytest.raises(RSIError, match="Global HOLD"):
        run_local_rsi_cycle(
            plan=plan, approval=make_approval(plan), runner=runner,
            evaluator=FakeIndependentEvaluator("REGRESSED"), executor=executor,
            sign_observation_digest=lambda digest: "attested:" + digest,
            created_at=123,
        )
    assert runner.calls == 0
    assert ledger.verify()

def test_evaluator_identity_mismatch_is_rejected_before_evaluation_record(tmp_path):
    class MismatchedEvaluator(FakeIndependentEvaluator):
        def evaluate(self, plan, result):
            self.calls += 1
            return IndependentEvaluation(
                plan.experiment_id, result.result_digest, "forged-evaluator",
                self.decision, "forged identity", "e" * 64, "evaluation-signature",
            )

    executor, ledger = make_executor(tmp_path)
    plan = make_plan()
    evaluator = MismatchedEvaluator("REGRESSED")
    with pytest.raises(RSIError, match="identity does not match"):
        run_local_rsi_cycle(
            plan=plan, approval=make_approval(plan), runner=FakeLocalRunner(),
            evaluator=evaluator, executor=executor,
            sign_observation_digest=lambda digest: "attested:" + digest,
            created_at=123,
        )
    with pytest.raises(RSIError, match="required evidence event is missing"):
        ledger.read_event("evaluation:" + plan.experiment_id)
    assert ledger.verify()

