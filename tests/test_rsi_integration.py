import hashlib
import hmac
import json

import pytest

from core.rsi_baseline import FrozenBaseline
from core.rsi_control import SignedRSIControlSnapshot, VerifiedRSIControlProvider
from core.rsi_executor import (
    EvidenceLedger, HumanApproval, Observation, RSIControl, RSIError, RSIExecutor,
    canonical_digest,
)
from core.rsi_local_evaluator import LocalRSIIndependentEvaluator
from core.rsi_local_runner import LocalRSIExperimentRunner, benchmark_protocol_digest


SECRET = b"test-only-rsi-signing-key"


def sign_digest(digest):
    return hmac.new(SECRET, digest.encode(), hashlib.sha256).hexdigest()


def verify_digest(digest, signature):
    return hmac.compare_digest(sign_digest(digest), signature)


def control_snapshot(now, *, execution_enabled, nonce):
    payload = {
        "global_hold": False,
        "execution_enabled": execution_enabled,
        "free_only": True,
        "budget_known": True,
        "budget_remaining_units": 4,
        "paid_fallback_enabled": False,
        "issued_at": now,
        "expires_at": now + 60,
        "nonce": nonce,
        "generation": 1,
    }
    digest = canonical_digest(payload)
    return SignedRSIControlSnapshot(**payload, signature=sign_digest(digest))


class FakeLocalClient:
    config = type("Config", (), {"model": "fixture-model"})()

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def chat(self, *, system, prompt):
        self.calls.append((system, prompt))
        return self.outputs.pop(0)


def build_pipeline(tmp_path, *, execution_enabled):
    now = 10_000
    ledger = EvidenceLedger(tmp_path / "integrated.sqlite")
    snapshot = control_snapshot(now, execution_enabled=execution_enabled, nonce="snapshot-1")
    control = VerifiedRSIControlProvider(
        lambda: snapshot, verify_signature=verify_digest,
        ledger=ledger, clock=lambda: now,
    )
    executor = RSIExecutor(
        ledger, control_provider=control,
        verify_approval=lambda approval: (
            approval.signature == "approval:" + approval.experiment_digest + ":" + approval.nonce
        ),
        verify_evidence_signature=verify_digest,
        verify_evaluation=lambda evaluation: verify_digest(
            canonical_digest({
                "experiment_id": evaluation.experiment_id,
                "result_digest": evaluation.result_digest,
                "evaluator_id": evaluation.evaluator_id,
                "decision": evaluation.decision,
                "rationale": evaluation.rationale,
                "evidence_digest": evaluation.evidence_digest,
            }),
            evaluation.signature,
        ),
        executor_id="rsi-executor",
    )
    return executor, ledger


def test_integrated_propose_approve_run_and_independent_evaluate(tmp_path):
    executor, ledger = build_pipeline(tmp_path, execution_enabled=True)
    observations = (
        Observation("int-obs-1", "a" * 64, "model", "FAIL", "quality fell", 1),
        Observation("int-obs-2", "b" * 64, "model", "REGRESSED", "quality repeated", 2),
    )
    observations = seed_observations(ledger, observations)
    diagnoses = executor.observe(observations)
    hypotheses = executor.hypothesize(diagnoses)
    candidate_digest = "c" * 64
    protocol_digest = benchmark_protocol_digest()
    baseline_unsigned = FrozenBaseline(
        "integration-baseline", "d" * 64, protocol_digest, 0.5, 100, 10_000, "pending"
    )
    baseline = FrozenBaseline(
        baseline_unsigned.baseline_id, baseline_unsigned.model_digest,
        baseline_unsigned.protocol_digest, baseline_unsigned.quality,
        baseline_unsigned.sample_count, baseline_unsigned.sealed_at,
        sign_digest(baseline_unsigned.digest),
    )
    plans = executor.plan(
        hypotheses, baseline_digest=baseline.digest,
        candidate_digest=candidate_digest, protocol_digest=protocol_digest,
        expected_cost_units=3,
    )
    plan = executor.select_next(plans)

    runner_client = FakeLocalClient(["RSI-READY", "SAFE-BOUNDARY", "EVIDENCE-LOCKED"])
    runner = LocalRSIExperimentRunner(
        runner_client, executor_id="rsi-executor", candidate_digest=candidate_digest, model_id="fixture-model", ledger=ledger,
    )
    approval = HumanApproval(
        "human-reviewer", plan.plan_digest, "once-1",
        "approval:" + plan.plan_digest + ":once-1",
    )
    result = executor.execute_approved(plan, approval, runner)

    evaluator_client = FakeLocalClient([json.dumps({
        "rationale": "All fixed benchmark checks passed."
    })])
    evaluator = LocalRSIIndependentEvaluator(
        evaluator_client, evaluator_id="independent-evaluator", ledger=ledger,
        baseline=baseline, verify_baseline_signature=verify_digest,
        sign_digest=sign_digest, clock=lambda: 10_000,
    )
    evaluation = evaluator.evaluate(plan, result)
    executor.evaluate(result, evaluation)

    assert result.metrics["quality"] == 1.0
    assert evaluation.evaluator_id != result.executor_id
    assert ledger.verify()
    assert len(runner_client.calls) == 3
    assert len(evaluator_client.calls) == 1


def test_execution_disabled_blocks_before_runner_invocation(tmp_path):
    executor, _ = build_pipeline(tmp_path, execution_enabled=False)
    observations = (
        Observation("off-obs-1", "a" * 64, "model", "FAIL", "quality fell", 1),
        Observation("off-obs-2", "b" * 64, "model", "REGRESSED", "quality repeated", 2),
    )
    observations = seed_observations(executor.ledger, observations)
    hypotheses = executor.hypothesize(executor.observe(observations))
    candidate = "c" * 64
    protocol = benchmark_protocol_digest()
    plan = executor.select_next(executor.plan(
        hypotheses, baseline_digest="d" * 64, candidate_digest=candidate,
        protocol_digest=protocol, expected_cost_units=3,
    ))
    client = FakeLocalClient(["should-not-run"])
    runner = LocalRSIExperimentRunner(
        client, executor_id="rsi-executor", candidate_digest=candidate, model_id="fixture-model", ledger=executor.ledger,
    )
    approval = HumanApproval(
        "human-reviewer", plan.plan_digest, "once-2",
        "approval:" + plan.plan_digest + ":once-2",
    )
    with pytest.raises(RSIError, match="execution is disabled"):
        executor.execute_approved(plan, approval, runner)
    assert client.calls == []



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
        seeded.append(replace(item, evidence_digest=digest, evidence_event_id=event_id))
    return tuple(seeded)
