import json

import pytest

from core.rsi_executor import (
    ExperimentPlan, ExperimentResult, RSIError, canonical_digest,
)
from core.rsi_local_evaluator import LocalRSIIndependentEvaluator


class FakeEvaluatorClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def chat(self, *, system, prompt):
        self.calls.append((system, prompt))
        return self.content


def make_plan():
    candidate = "b" * 64
    payload = {
        "hypothesis": "hypothesis-id", "capability": "model",
        "baseline": "a" * 64, "candidate": candidate, "protocol": "c" * 64,
        "cost": 1, "risk": 0.1, "information_value": 0.5,
    }
    digest = canonical_digest(payload)
    return ExperimentPlan(digest[:32], "hypothesis-id", "model", "a" * 64,
                          candidate, "c" * 64, 1, 0.1, 0.5, digest)


def make_result(plan, executor_id="local-runner"):
    evidence = "d" * 64
    metrics = {"quality": 1.0}
    digest = canonical_digest({
        "experiment_id": plan.experiment_id,
        "executor_id": executor_id,
        "evidence_digest": evidence,
        "metrics": metrics,
    })
    return ExperimentResult(plan.experiment_id, executor_id, digest, metrics, evidence)


def test_independent_evaluator_returns_signed_result_bound_to_exact_digest():
    plan = make_plan()
    result = make_result(plan)
    client = FakeEvaluatorClient(json.dumps({
        "decision": "IMPROVED", "rationale": "Frozen benchmark score increased."
    }))
    signed = []
    evaluator = LocalRSIIndependentEvaluator(
        client, evaluator_id="separate-evaluator",
        sign_digest=lambda digest: signed.append(digest) or "signed:" + digest,
    )
    evaluation = evaluator.evaluate(plan, result)
    assert evaluation.experiment_id == plan.experiment_id
    assert evaluation.result_digest == result.result_digest
    assert evaluation.evaluator_id != result.executor_id
    assert evaluation.decision == "IMPROVED"
    assert signed == [signed[0]]
    assert evaluation.signature.startswith("signed:")
    assert len(evaluation.evidence_digest) == 64


def test_evaluator_rejects_executor_identity_and_unbound_result():
    plan = make_plan()
    result = make_result(plan, executor_id="same-identity")
    evaluator = LocalRSIIndependentEvaluator(
        FakeEvaluatorClient("{}"), evaluator_id="same-identity",
        sign_digest=lambda _: "sig",
    )
    with pytest.raises(RSIError, match="identities must differ"):
        evaluator.evaluate(plan, result)
    other = ExperimentResult("different", result.executor_id, result.result_digest,
                             result.metrics, result.evidence_digest)
    evaluator = LocalRSIIndependentEvaluator(
        FakeEvaluatorClient("{}"), evaluator_id="independent",
        sign_digest=lambda _: "sig",
    )
    with pytest.raises(RSIError, match="does not bind"):
        evaluator.evaluate(plan, other)


def test_evaluator_rejects_extra_authority_fields_and_bad_signatures():
    plan, result = make_plan(), None
    result = make_result(plan)
    client = FakeEvaluatorClient(json.dumps({
        "decision": "IMPROVED", "rationale": "ok", "execution_authorized": True
    }))
    evaluator = LocalRSIIndependentEvaluator(
        client, evaluator_id="independent", sign_digest=lambda _: "sig"
    )
    with pytest.raises(RSIError, match="unexpected schema"):
        evaluator.evaluate(plan, result)
    evaluator = LocalRSIIndependentEvaluator(
        FakeEvaluatorClient(json.dumps({"decision": "IMPROVED", "rationale": "ok"})),
        evaluator_id="independent", sign_digest=lambda _: "",
    )
    with pytest.raises(RSIError, match="invalid signature"):
        evaluator.evaluate(plan, result)
