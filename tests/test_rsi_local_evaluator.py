import json

import pytest

from core.rsi_executor import (
    EvidenceLedger, ExperimentPlan, ExperimentResult, RSIError, canonical_digest,
)
from core.rsi_local_evaluator import LocalRSIIndependentEvaluator
from core.rsi_local_runner import BenchmarkCase, LocalRSIExperimentRunner, benchmark_protocol_digest


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def chat(self, *, system, prompt):
        self.calls.append((system, prompt))
        return self.content


def make_plan():
    candidate = "b" * 64
    cases = (BenchmarkCase("one", "say token", "TOKEN"),)
    protocol = benchmark_protocol_digest(cases)
    payload = {
        "hypothesis": "hypothesis-id", "capability": "model",
        "baseline": "a" * 64, "candidate": candidate, "protocol": protocol,
        "cost": 1, "risk": 0.1, "information_value": 0.5,
    }
    digest = canonical_digest(payload)
    plan = ExperimentPlan(
        digest[:32], "hypothesis-id", "model", "a" * 64, candidate,
        protocol, 1, 0.1, 0.5, digest,
    )
    return plan, cases


def make_result(tmp_path, output="TOKEN"):
    plan, cases = make_plan()
    ledger = EvidenceLedger(tmp_path / "evaluator.sqlite")
    runner = LocalRSIExperimentRunner(
        FakeClient([output]), executor_id="local-runner",
        candidate_digest=plan.candidate_digest, ledger=ledger, cases=cases,
    )
    result = runner(plan)
    return plan, result, ledger


def make_evaluator(ledger, client, signer=lambda _: "signature", baseline_quality=0.0):
    return LocalRSIIndependentEvaluator(
        client, evaluator_id="separate-evaluator", ledger=ledger,
        baseline_quality=baseline_quality, sign_digest=signer,
    )


def test_independent_evaluator_recomputes_evidence_and_signs_result(tmp_path):
    plan, result, ledger = make_result(tmp_path)
    client = FakeClient(json.dumps({"rationale": "Frozen benchmark score increased."}))
    signed = []
    evaluator = make_evaluator(
        ledger, client,
        signer=lambda digest: signed.append(digest) or "signed:" + digest,
        baseline_quality=0.0,
    )
    evaluation = evaluator.evaluate(plan, result)
    assert evaluation.experiment_id == plan.experiment_id
    assert evaluation.result_digest == result.result_digest
    assert evaluation.evaluator_id != result.executor_id
    assert evaluation.decision == "IMPROVED"
    assert len(signed) == 1
    assert evaluation.signature.startswith("signed:")
    assert len(evaluation.evidence_digest) == 64


def test_evaluator_rejects_executor_identity_and_unbound_result(tmp_path):
    plan, result, ledger = make_result(tmp_path)
    same = LocalRSIIndependentEvaluator(
        FakeClient("{}"), evaluator_id="local-runner", ledger=ledger,
        baseline_quality=0.0, sign_digest=lambda _: "sig",
    )
    with pytest.raises(RSIError, match="identities must differ"):
        same.evaluate(plan, result)
    other = ExperimentResult("different", result.executor_id, result.result_digest,
                             result.metrics, result.evidence_digest)
    evaluator = make_evaluator(ledger, FakeClient("{}"))
    with pytest.raises(RSIError, match="does not bind"):
        evaluator.evaluate(plan, other)


def test_evaluator_rejects_model_authority_fields_and_bad_signatures(tmp_path):
    plan, result, ledger = make_result(tmp_path)
    client = FakeClient(json.dumps({"rationale": "ok", "execution_authorized": True}))
    with pytest.raises(RSIError, match="unexpected schema"):
        make_evaluator(ledger, client).evaluate(plan, result)
    evaluator = make_evaluator(
        ledger, FakeClient(json.dumps({"rationale": "ok"})), signer=lambda _: ""
    )
    with pytest.raises(RSIError, match="invalid signature"):
        evaluator.evaluate(plan, result)


def test_evaluator_rejects_tampered_metrics_even_with_same_result_digest(tmp_path):
    plan, result, ledger = make_result(tmp_path)
    tampered = ExperimentResult(
        result.experiment_id, result.executor_id, result.result_digest,
        {"quality": 0.0, "case_count": 1.0}, result.evidence_digest,
    )
    evaluator = make_evaluator(
        ledger, FakeClient(json.dumps({"rationale": "should not be reached"}))
    )
    with pytest.raises(RSIError, match="independently recomputed"):
        evaluator.evaluate(plan, tampered)
