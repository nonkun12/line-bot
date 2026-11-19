from core.idea_ai import IdeaAgent
from core.multi_agent import AgentRole

def test_idea_agent_is_bounded_and_non_executing():
    ideas = IdeaAgent().propose("Hand-Sign AI", context=("UHIP", "free", "fail-closed"))
    assert len(ideas) == 5
    assert all(item.task.role is AgentRole.IDEA for item in ideas)
    assert all("No implementation, execution, merge, deploy" in item.task.instruction for item in ideas)

def test_idea_agent_rejects_invalid_input():
    import pytest
    with pytest.raises(ValueError):
        IdeaAgent().propose("")
    with pytest.raises(ValueError):
        IdeaAgent().propose("Loop", limit=6)



def test_idea_agent_accepts_only_verified_evidence_ledger_learning_signals():
    from core.idea_evidence import (
        EvidenceVerification,
        ExperimentEvidence,
        ExperimentEvidenceLedger,
    )

    ledger = ExperimentEvidenceLedger()
    verification = EvidenceVerification(
        verifier="independent-review",
        verification_ref="review://benchmark/verified",
        verified_at="2026-11-19T00:00:00Z",
        checks=("artifact digest inspected",),
    )
    for index in range(10):
        ledger = ledger.append(ExperimentEvidence(
            hypothesis_id=f"recombine-{index}",
            style="recombine",
            result="success",
            observed_value=1.0,
            metric="validated result rate",
            source_ref=f"artifact://run/recombine/{index}",
            commit_sha="a" * 40,
            environment="fixed-test-environment",
            sample_count=10,
            measured_at="2026-11-19T00:00:00Z",
            evidence_sha256=f"{index:064x}",
            verification=verification,
        ))
    for style in ("reframe", "specialize", "architecture-leap", "constraint"):
        for index in range(10):
            ledger = ledger.append(ExperimentEvidence(
                hypothesis_id=f"{style}-{index}",
                style=style,
                result="failure",
                observed_value=0.0,
                metric="validated result rate",
                source_ref=f"artifact://run/{style}/{index}",
                commit_sha="b" * 40,
                environment="fixed-test-environment",
                sample_count=10,
                measured_at="2026-11-19T00:00:00Z",
                evidence_sha256=f"{index + 100:064x}",
                verification=verification,
            ))

    ideas = IdeaAgent().propose("improve research", outcomes=ledger.learning_outcomes())
    assert ideas[0].style == "recombine"


def test_idea_agent_uses_explicit_local_client_and_validates_structured_output():
    import json
    from core.idea_learning import IdeaOutcome
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured["prompt"] = kwargs["messages"][1]["content"]
            assert kwargs["model"] == "test-local"
            assert kwargs["response_format"]["type"] == "json_schema"
            payload = {"ideas": [{
                "style": "novel-path",
                "title": "新しい探索経路",
                "rationale": "異なる制約を組み合わせる",
                "next_step": "小さな比較実験の計画を作る",
                "novelty": 5,
                "positive_impact": "探索効率を高める",
            }]}
            from types import SimpleNamespace
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
            )])

    class Client:
        model = "test-local"
        chat = type("Chat", (), {"completions": Completions()})()

    outcomes = (
        IdeaOutcome("verified-style", "success", "verified benchmark improved"),
        IdeaOutcome("failed-style", "failure", "verified benchmark regressed"),
        IdeaOutcome("unverified-style", "unverified", "not independently checked"),
    )
    ideas = IdeaAgent().propose(
        "自立開発", limit=1, local_client=Client(), outcomes=outcomes
    )
    assert "verified-style" in captured["prompt"]
    assert "failed-style" in captured["prompt"]
    assert "unverified-style" not in captured["prompt"]
    assert len(ideas) == 1
    assert ideas[0].title == "新しい探索経路"
    assert ideas[0].task.role is AgentRole.IDEA
    assert "No implementation, execution, merge, deploy" in ideas[0].task.instruction


def test_idea_agent_rejects_unsafe_or_malformed_local_model_output():
    from types import SimpleNamespace
    import pytest

    class Completions:
        def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"ideas":[{"style":"../unsafe"}]}')
            )])

    class Client:
        model = "test-local"
        chat = type("Chat", (), {"completions": Completions()})()

    with pytest.raises(ValueError):
        IdeaAgent().propose("自立開発", limit=1, local_client=Client())
