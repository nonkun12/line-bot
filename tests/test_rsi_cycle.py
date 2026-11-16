from core.rsi_cycle import run_proposal_cycle
from core.rsi_executor import EvidenceLedger, Observation, RSIControl, RSIExecutor


class RecordingAdvisor:
    def __init__(self):
        self.calls = []

    def advise(self, diagnosis, hypothesis):
        self.calls.append((diagnosis.diagnosis_id, hypothesis.hypothesis_id))
        return {"proposal_only": True, "execution_authorized": False}


def make_executor(tmp_path):
    ledger = EvidenceLedger(tmp_path / "cycle.sqlite")
    return RSIExecutor(
        ledger,
        control_provider=lambda: RSIControl(False, False, True, True, 5, False),
        verify_approval=lambda _: False,
        verify_evaluation=lambda _: False,
        verify_evidence_signature=lambda digest, signature: signature == "sig:" + digest,
        executor_id="rsi-planner",
    ), ledger


def test_proposal_cycle_runs_end_to_end_without_execution(tmp_path):
    executor, ledger = make_executor(tmp_path)
    advisor = RecordingAdvisor()
    observations = (
        Observation("cycle-obs-1", "a" * 64, "model", "FAIL", "quality fell", 1),
        Observation("cycle-obs-2", "b" * 64, "model", "REGRESSED", "repeat regression", 2),
    )
    observations = seed_observations(ledger, observations)
    cycle = run_proposal_cycle(
        executor,
        observations,
        baseline_digest="c" * 64,
        candidate_digest="d" * 64,
        protocol_digest="e" * 64,
        expected_cost_units=2,
        advisor=advisor,
    )
    assert cycle.status == "PROPOSAL_READY"
    assert cycle.selected_plan in cycle.plans
    assert len(cycle.diagnoses) == len(cycle.hypotheses) == len(advisor.calls) == 1
    assert cycle.execution_authorized is False
    assert cycle.human_approval_granted is False
    assert cycle.evaluation_certified is False
    assert cycle.model_activated is False
    assert ledger.verify()


def test_pass_only_cycle_stops_without_inventing_a_hypothesis(tmp_path):
    executor, ledger = make_executor(tmp_path)
    observations = seed_observations(ledger, (Observation("pass-obs", "a" * 64, "model", "PASS", "baseline stable", 1),))
    cycle = run_proposal_cycle(
        executor,
        observations,
        baseline_digest="b" * 64,
        candidate_digest="c" * 64,
        protocol_digest="d" * 64,
    )
    assert cycle.status == "NO_IMPROVEMENT_TARGET"
    assert cycle.selected_plan is None
    assert cycle.hypotheses == ()
    assert ledger.verify()


def test_advisor_failure_cannot_authorize_execution(tmp_path):
    executor, _ = make_executor(tmp_path)

    class BrokenAdvisor:
        def advise(self, diagnosis, hypothesis):
            raise RuntimeError("local model unavailable")

    observations = seed_observations(executor.ledger, (Observation("fail-obs", "a" * 64, "model", "FAIL", "quality fell", 1),))
    try:
        run_proposal_cycle(
            executor,
            observations,
            baseline_digest="b" * 64,
            candidate_digest="c" * 64,
            protocol_digest="d" * 64,
            advisor=BrokenAdvisor(),
        )
    except RuntimeError as exc:
        assert str(exc) == "local model unavailable"
    else:
        raise AssertionError("advisor failure should stop proposal cycle")



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
