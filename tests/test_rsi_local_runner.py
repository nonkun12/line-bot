import pytest

from core.rsi_executor import ExperimentPlan, RSIError, canonical_digest
from core.rsi_local_runner import (
    BenchmarkCase, LocalRSIExperimentRunner, benchmark_protocol_digest,
)


class FakeLocalClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def chat(self, *, system, prompt):
        self.calls.append((system, prompt))
        return self.outputs.pop(0)


def plan(candidate, protocol, cost=2, capability="model"):
    payload = {
        "hypothesis": "hypothesis-id", "capability": capability,
        "baseline": "a" * 64, "candidate": candidate, "protocol": protocol,
        "cost": cost, "risk": 0.1, "information_value": 0.5,
    }
    digest = canonical_digest(payload)
    return ExperimentPlan(
        digest[:32], "hypothesis-id", capability, "a" * 64, candidate,
        protocol, cost, 0.1, 0.5, digest,
    )


def test_runner_executes_only_fixed_loopback_benchmark_cases():
    candidate = "b" * 64
    cases = (
        BenchmarkCase("one", "say token A", "TOKEN-A"),
        BenchmarkCase("two", "say token B", "TOKEN-B"),
    )
    client = FakeLocalClient(["TOKEN-A", "wrong"])
    runner = LocalRSIExperimentRunner(
        client, executor_id="local-runner", candidate_digest=candidate, cases=cases
    )
    result = runner(plan(candidate, benchmark_protocol_digest(cases)))
    assert runner.is_local is True
    assert runner.paid_fallback_enabled is False
    assert result.metrics == {"quality": 0.5, "case_count": 2.0}
    assert len(client.calls) == 2
    assert len(result.result_digest) == len(result.evidence_digest) == 64


def test_runner_rejects_unbound_candidate_or_protocol():
    candidate = "b" * 64
    cases = (BenchmarkCase("one", "say token A", "TOKEN-A"),)
    runner = LocalRSIExperimentRunner(
        FakeLocalClient(["TOKEN-A"]), executor_id="local-runner",
        candidate_digest=candidate, cases=cases,
    )
    with pytest.raises(RSIError, match="candidate digest"):
        runner(plan("c" * 64, runner.protocol_digest, cost=1))
    with pytest.raises(RSIError, match="protocol digest"):
        runner(plan(candidate, "d" * 64, cost=1))


def test_runner_rejects_unbounded_or_wrong_capability_plan():
    candidate = "b" * 64
    cases = (BenchmarkCase("one", "say token A", "TOKEN-A"),)
    runner = LocalRSIExperimentRunner(
        FakeLocalClient(["TOKEN-A"]), executor_id="local-runner",
        candidate_digest=candidate, cases=cases,
    )
    with pytest.raises(RSIError, match="only supports model"):
        runner(plan(candidate, runner.protocol_digest, cost=1, capability="evaluator"))
    with pytest.raises(ValueError, match="1..4"):
        LocalRSIExperimentRunner(
            FakeLocalClient([]), executor_id="local-runner",
            candidate_digest=candidate, cases=tuple(
                BenchmarkCase(str(i), "prompt", "expected") for i in range(5)
            ),
        )
