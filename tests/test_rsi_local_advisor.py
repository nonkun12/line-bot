import json

import pytest

from core.rsi_executor import EvidenceLedger, Observation, RSIControl, RSIExecutor
from core.rsi_local_advisor import LocalRSIAdvisor, build_loopback_rsi_advisor


class FakeLocalModel:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def chat(self, *, system, prompt):
        self.calls.append((system, prompt))
        return self.content


def make_cycle(tmp_path):
    ledger = EvidenceLedger(tmp_path / "advisor.sqlite")
    executor = RSIExecutor(
        ledger,
        control_provider=lambda: RSIControl(False, False, True, True, 5, False),
        verify_approval=lambda _: False,
        verify_evaluation=lambda _: False,
        verify_evidence_signature=lambda digest, signature: signature == "sig:" + digest,
        executor_id="rsi-planner",
    )
    observations = (
        Observation("advisor-obs-1", "a" * 64, "model", "FAIL", "quality regressed", 1),
        Observation("advisor-obs-2", "b" * 64, "model", "REGRESSED", "repeat regression", 2),
    )
    observations = seed_observations(ledger, observations)
    diagnosis = executor.observe(observations)[0]
    hypothesis = executor.hypothesize((diagnosis,))[0]
    return ledger, diagnosis, hypothesis


def test_local_advisor_adds_proposal_only_note_without_execution(tmp_path):
    ledger, diagnosis, hypothesis = make_cycle(tmp_path)
    model = FakeLocalModel(json.dumps({
        "alternative_hypothesis": "Tokenizer mismatch causes the quality drop.",
        "falsification_test": "Repeat the frozen suite with tokenizer fingerprint pinned.",
        "uncertainty": "The current evidence does not isolate tokenizer effects.",
    }))
    note = LocalRSIAdvisor(model, ledger, model_id="lfm3-local").advise(diagnosis, hypothesis)
    assert note.proposal_only is True
    assert note.execution_authorized is False
    assert note.evaluation_certified is False
    assert note.approval_granted is False
    assert note.model_activated is False
    assert len(model.calls) == 1
    assert ledger.verify()


def test_local_advisor_rejects_extra_authority_fields(tmp_path):
    ledger, diagnosis, hypothesis = make_cycle(tmp_path)
    model = FakeLocalModel(json.dumps({
        "alternative_hypothesis": "A",
        "falsification_test": "B",
        "uncertainty": "C",
        "approved": True,
    }))
    with pytest.raises(ValueError, match="unexpected schema"):
        LocalRSIAdvisor(model, ledger, model_id="lfm3-local").advise(diagnosis, hypothesis)


def test_local_advisor_rejects_cross_wired_hypothesis(tmp_path):
    ledger, diagnosis, hypothesis = make_cycle(tmp_path)
    model = FakeLocalModel("{}")
    from dataclasses import replace
    with pytest.raises(ValueError, match="does not bind"):
        LocalRSIAdvisor(model, ledger, model_id="lfm3-local").advise(
            diagnosis, replace(hypothesis, diagnosis_id="other-diagnosis")
        )


def test_loopback_builder_pins_local_endpoint_and_small_output():
    class DummyLedger:
        pass
    advisor = build_loopback_rsi_advisor(model="lfm3:1.7b-qad-q4_0", ledger=DummyLedger())
    assert advisor._client.config.base_url == "http://127.0.0.1:11434"
    assert advisor._client.config.max_output_tokens == 512


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
        seeded.append(replace(
            item, evidence_digest=digest, evidence_event_id=event_id,
            experiment_id="source-" + item.observation_id,
            candidate_digest="c" * 64, protocol_digest="d" * 64, result_digest="e" * 64,
        ))
    return tuple(seeded)
