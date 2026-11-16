from dataclasses import replace

import pytest

from core.creator_critic import CriticAgent, CreatorAgent
from core.rsi_executor import EvidenceLedger, Observation, RSIControl, RSIExecutor, RSIError
from core.rsi_orchestra import run_orchestra_rsi_batch
from core.rsi_supervisor import RSIProposalInput

HEAD = "a" * 40


def make_executor(tmp_path):
    return RSIExecutor(
        EvidenceLedger(tmp_path / "orchestra.sqlite"),
        control_provider=lambda: RSIControl(True, False, True, True, 10, False),
        verify_approval=lambda _: False,
        verify_evaluation=lambda _: False,
        verify_evidence_signature=lambda producer_id, digest, signature:
            producer_id == "test-producer" and signature == "sig:" + digest,
        executor_id="orchestra-proposal-only",
    )


def make_input(index=1):
    observation = Observation(
        f"orchestra-{index}", str(index % 10) * 64, "local-model",
        "FAIL", "fixed benchmark evidence", index,
    )
    return RSIProposalInput(
        (observation,), "a" * 64, "b" * 64, "c" * 64, 1,
    )


def seed_input(executor, item):
    observation = item.observations[0]
    event_id = "source:" + observation.observation_id
    digest = executor.ledger.append_observation_evidence(
        event_id,
        observation=observation,
        experiment_id="source-" + observation.observation_id,
        candidate_digest="c" * 64,
        protocol_digest="d" * 64,
        result_digest="e" * 64,
        producer_id="test-producer",
        sign_digest=lambda value: "sig:" + value,
    )
    return replace(item, observations=(replace(
        observation,
        evidence_digest=digest,
        evidence_event_id=event_id,
        experiment_id="source-" + observation.observation_id,
        candidate_digest="c" * 64,
        protocol_digest="d" * 64,
        result_digest="e" * 64,
    ),))


def make_agents(*, critic_calls=None):
    def creator_model(_prompt):
        return "Propose a minimal falsifiable benchmark improvement."

    def critic_model(_prompt):
        if critic_calls is not None:
            critic_calls.append("critic")
        return "Reviewed against independently verified test evidence."

    return CreatorAgent(creator_model), CriticAgent(critic_model)


def test_orchestra_binds_rea_review_to_exact_head_plan_candidate_and_evidence(tmp_path):
    executor = make_executor(tmp_path)
    source = seed_input(executor, make_input())
    creator, critic = make_agents()
    seen = {}

    def evidence_provider(plan, candidate):
        seen["plan"] = plan
        seen["candidate"] = candidate
        return {
            "accuracy": 1.0,
            "stability": 1.0,
            "efficiency": 0.9,
            "safety": 1.0,
            "evidence_ref": "pytest://run/verified-1",
        }

    def verify_evidence(evidence, binding):
        return (
            evidence["evidence_ref"] == "pytest://run/verified-1"
            and binding["head_sha"] == HEAD
            and binding["plan_digest"] == seen["plan"].plan_digest
            and binding["experiment_id"] == seen["plan"].experiment_id
            and binding["candidate_digest"]
        )

    result = run_orchestra_rsi_batch(
        executor, lambda: source, creator=creator, critic=critic,
        repository="nonkun12/line-bot", head_sha=HEAD,
        objective="improve the local benchmark safely",
        evidence_provider=evidence_provider, verify_evidence=verify_evidence,
        max_cycles=1,
    )

    assert result.status == "REVIEW_PASS_PROPOSAL_ONLY"
    assert len(result.reviews) == 1
    review = result.reviews[0]
    assert review.status == "PASS"
    assert review.handoff.head_sha == HEAD
    assert review.handoff.plan_digest == seen["plan"].plan_digest
    assert review.handoff.candidate_digest
    assert review.handoff.evidence_digest
    assert review.evaluation is not None and review.evaluation.passed
    assert result.dispatch_authorized is False
    assert result.execution_authorized is False
    assert result.scheduler_started is False
    assert result.model_activated is False


def test_unverified_evidence_blocks_before_critic_is_called(tmp_path):
    executor = make_executor(tmp_path)
    source = seed_input(executor, make_input())
    calls = []
    creator, critic = make_agents(critic_calls=calls)

    result = run_orchestra_rsi_batch(
        executor, lambda: source, creator=creator, critic=critic,
        repository="nonkun12/line-bot", head_sha=HEAD,
        objective="test blocked evidence",
        evidence_provider=lambda _plan, _candidate: {
            "accuracy": 1.0, "stability": 1.0, "efficiency": 1.0,
            "safety": 1.0, "evidence_ref": "untrusted",
        },
        verify_evidence=lambda _evidence, _binding: False,
        max_cycles=1,
    )

    assert result.status == "BLOCKED"
    assert result.reviews[0].status == "BLOCKED"
    assert result.reviews[0].reason_code == "evidence_verification_failed"
    assert calls == []
    assert result.execution_authorized is False


def test_creator_and_critic_cannot_share_the_same_model_callable(tmp_path):
    executor = make_executor(tmp_path)
    source = seed_input(executor, make_input())
    shared = lambda _prompt: "shared model output"
    with pytest.raises(RSIError, match="distinct model-call identities"):
        run_orchestra_rsi_batch(
            executor, lambda: source,
            creator=CreatorAgent(shared), critic=CriticAgent(shared),
            repository="nonkun12/line-bot", head_sha=HEAD,
            objective="test role separation",
            evidence_provider=lambda _plan, _candidate: {},
            verify_evidence=lambda _evidence, _binding: True,
            max_cycles=1,
        )


def test_critic_failure_remains_review_required_and_never_authorizes(tmp_path):
    executor = make_executor(tmp_path)
    source = seed_input(executor, make_input())
    creator, critic = make_agents()

    result = run_orchestra_rsi_batch(
        executor, lambda: source, creator=creator, critic=critic,
        repository="nonkun12/line-bot", head_sha=HEAD,
        objective="test critic failure",
        evidence_provider=lambda _plan, _candidate: {
            "accuracy": 0.9, "stability": 0.9, "efficiency": 0.9,
            "safety": 0.2, "evidence_ref": "pytest://run/unsafe",
        },
        verify_evidence=lambda _evidence, binding: binding["head_sha"] == HEAD,
        max_cycles=1,
    )

    assert result.status == "REVIEW_REQUIRED"
    assert result.reviews[0].status == "FAIL"
    assert result.reviews[0].evaluation is not None
    assert result.reviews[0].evaluation.passed is False
    assert result.reviews[0].patch_authorized is False
    assert result.reviews[0].hold_clear_authorized is False


def test_orchestra_rejects_unbound_repository_or_head_before_running(tmp_path):
    executor = make_executor(tmp_path)
    source = seed_input(executor, make_input())
    creator, critic = make_agents()
    kwargs = dict(
        executor=executor, input_source=lambda: source,
        creator=creator, critic=critic, repository="nonkun12/line-bot",
        objective="reject bad SHA",
        evidence_provider=lambda _plan, _candidate: {},
        verify_evidence=lambda _evidence, _binding: True,
        max_cycles=1,
    )
    with pytest.raises(RSIError, match="exact repository HEAD SHA"):
        run_orchestra_rsi_batch(**kwargs, head_sha="not-a-sha")
