from core.creator_critic import CriticAgent, CreatorAgent, CreatorCriticLoop, ImprovementCandidate


def test_creator_generates_bounded_candidate():
    creator = CreatorAgent(lambda prompt: "Improve the verifier with a regression test.")
    candidate = creator.create("improve verifier", {"accuracy": 0.7}, iteration=1)
    assert candidate.candidate_id == "creator-1"
    assert "regression" in candidate.proposal
    assert "must be testable" in candidate.constraints


def test_critic_uses_external_evidence_and_fails_closed_on_missing_metrics():
    seen = {}

    def model(prompt):
        seen["prompt"] = prompt
        return "Evidence is reproducible enough for the next experiment."

    critic = CriticAgent(model)
    candidate = ImprovementCandidate("c1", "objective", "proposal")
    result = critic.evaluate(candidate, {"accuracy": 0.9, "stability": 0.8, "efficiency": 0.5, "safety": 1.0, "candidate_evaluated": True})
    assert result.passed is True
    assert result.score == 0.84
    assert "0.9" in seen["prompt"]

    missing = critic.evaluate(candidate, {})
    assert missing.passed is False
    assert missing.score == 0.0


def test_critic_requires_candidate_specific_evidence_even_with_high_metrics():
    critic = CriticAgent(lambda prompt: "looks good")
    candidate = ImprovementCandidate("c2", "objective", "proposal")
    result = critic.evaluate(
        candidate,
        {"accuracy": 1.0, "stability": 1.0, "efficiency": 1.0, "safety": 1.0},
    )
    assert result.score == 1.0
    assert result.passed is False


def test_duel_uses_fresh_evidence_for_each_candidate():
    seen = []

    creator = CreatorAgent(lambda prompt: "candidate")
    critic = CriticAgent(lambda prompt: "evaluation")
    loop = CreatorCriticLoop(creator, critic, max_iterations=3)

    def evidence_provider(candidate):
        seen.append(candidate.candidate_id)
        if len(seen) == 1:
            return {"accuracy": 0.0, "stability": 0.0, "efficiency": 0.5, "safety": 1.0, "candidate_evaluated": True}
        return {"accuracy": 1.0, "stability": 1.0, "efficiency": 1.0, "safety": 1.0, "candidate_evaluated": True}

    results = loop.run("improve reliability", evidence_provider)

    assert seen == ["creator-1", "creator-2"]
    assert len(results) == 2
    assert results[-1].evaluation.passed is True
    assert missing.score == 0.0


def test_duel_stops_when_critic_passes():
    creator_calls = []
    critic = CriticAgent(lambda prompt: "accepted")
    creator = CreatorAgent(lambda prompt: creator_calls.append(prompt) or "candidate")
    loop = CreatorCriticLoop(creator, critic, max_iterations=3)
    results = loop.run(
        "improve reliability",
        lambda candidate: {"accuracy": 0.9, "stability": 0.9, "efficiency": 0.7, "safety": 1.0},
    )
    assert len(results) == 1
    assert results[0].evaluation.passed is True
    assert len(creator_calls) == 1


def test_duel_is_bounded_and_refeeds_critic_feedback():
    prompts = []
    critic = CriticAgent(lambda prompt: "try a smaller change")
    creator = CreatorAgent(lambda prompt: prompts.append(prompt) or "candidate")
    loop = CreatorCriticLoop(creator, critic, max_iterations=3)
    results = loop.run(
        "improve reliability",
        lambda candidate: {"accuracy": 0.4, "stability": 0.5, "efficiency": 0.4, "safety": 1.0},
    )
    assert len(results) == 3
    assert "try a smaller change" in prompts[1]
    assert "try a smaller change" in prompts[2]
