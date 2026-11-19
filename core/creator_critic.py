"""Creator/Critic pair for bounded, evidence-driven self-improvement.

The pair is deliberately provider-neutral. A model adapter is injected as a
callable; this module owns contracts, prompt boundaries, evidence handling,
and the bounded feedback loop. Neither agent can mutate the repository.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping


ModelCall = Callable[[str], str]


@dataclass(frozen=True)
class ImprovementCandidate:
    """A Creator proposal that can be tested without mutating the live system."""

    candidate_id: str
    objective: str
    proposal: str
    constraints: tuple[str, ...] = ()
    evidence: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, name in ((self.candidate_id, "candidate_id"), (self.objective, "objective"), (self.proposal, "proposal")):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")


@dataclass(frozen=True)
class CriticEvaluation:
    """Evidence-based evaluation returned by the Critic."""

    candidate_id: str
    passed: bool
    score: float
    accuracy: float
    stability: float
    efficiency: float
    safety: float
    feedback: str
    evidence: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0 and 1")
        for value, name in ((self.accuracy, "accuracy"), (self.stability, "stability"), (self.efficiency, "efficiency"), (self.safety, "safety")):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if not self.feedback.strip():
            raise ValueError("feedback is required")


@dataclass(frozen=True)
class DuelResult:
    """One Creator -> external evidence -> Critic cycle."""

    candidate: ImprovementCandidate
    evaluation: CriticEvaluation
    next_instruction: str


class CreatorAgent:
    """Generate a bounded improvement candidate from objective and evidence."""

    def __init__(self, model: ModelCall, *, max_output_chars: int = 12000) -> None:
        if not callable(model):
            raise TypeError("model must be callable")
        if max_output_chars < 1:
            raise ValueError("max_output_chars must be >= 1")
        self._model = model
        self._max_output_chars = max_output_chars

    def create(self, objective: str, evidence: Mapping[str, object] | None = None, *, iteration: int = 1) -> ImprovementCandidate:
        if not objective.strip():
            raise ValueError("objective is required")
        if iteration < 1:
            raise ValueError("iteration must be >= 1")
        prompt = (
            "You are CREATOR, the improvement-generating AI.\n"
            "Propose one minimal, testable improvement. Use external evidence; "
            "never assume your own output is correct. Do not request secrets, "
            "permissions, destructive operations, or direct production mutation.\n"
            f"Objective: {objective.strip()}\n"
            f"Evidence: {dict(evidence or {})}\n"
            f"Iteration: {iteration}\n"
            "Return a concise proposal suitable for a separate Critic and test runner."
        )
        proposal = self._model(prompt).strip()
        if not proposal:
            raise ValueError("creator returned an empty proposal")
        return ImprovementCandidate(
            candidate_id=f"creator-{iteration}",
            objective=objective.strip(),
            proposal=proposal[: self._max_output_chars],
            constraints=(
                "must be testable",
                "must preserve protected configuration and secrets",
                "must pass existing review and integration gates",
            ),
            evidence=dict(evidence or {}),
        )


class CriticAgent:
    """Evaluate Creator output using supplied execution evidence."""

    def __init__(self, model: ModelCall, *, max_output_chars: int = 12000) -> None:
        if not callable(model):
            raise TypeError("model must be callable")
        if max_output_chars < 1:
            raise ValueError("max_output_chars must be >= 1")
        self._model = model
        self._max_output_chars = max_output_chars

    def evaluate(self, candidate: ImprovementCandidate, evidence: Mapping[str, object] | None = None) -> CriticEvaluation:
        observed = dict(candidate.evidence)
        observed.update(evidence or {})
        prompt = (
            "You are CRITIC, the independent evaluation AI.\n"
            "Judge the Creator proposal against observed execution evidence. "
            "Do not reward persuasive prose. Prefer reproducible tests, external "
            "results, stability, efficiency, and safety. Identify weaknesses and "
            "give a concrete next experiment.\n"
            f"Candidate: {candidate.proposal}\n"
            f"Evidence: {observed}\n"
            "Return concise evaluation notes."
        )
        feedback = self._model(prompt).strip()
        if not feedback:
            raise ValueError("critic returned empty feedback")
        metrics = _evidence_metrics(observed)
        score = (
            0.35 * metrics["accuracy"]
            + 0.25 * metrics["stability"]
            + 0.15 * metrics["efficiency"]
            + 0.25 * metrics["safety"]
        )
        passed = metrics["safety"] >= 0.8 and metrics["accuracy"] >= 0.6 and metrics["stability"] >= 0.6
        return CriticEvaluation(
            candidate_id=candidate.candidate_id,
            passed=passed,
            score=round(score, 4),
            accuracy=metrics["accuracy"],
            stability=metrics["stability"],
            efficiency=metrics["efficiency"],
            safety=metrics["safety"],
            feedback=feedback[: self._max_output_chars],
            evidence=observed,
        )


class CreatorCriticLoop:
    """Bounded duel: Creator proposes, evidence is measured, Critic evaluates."""

    def __init__(self, creator: CreatorAgent, critic: CriticAgent, *, max_iterations: int = 3) -> None:
        if max_iterations < 1 or max_iterations > 3:
            raise ValueError("max_iterations must be between 1 and 3")
        self.creator = creator
        self.critic = critic
        self.max_iterations = max_iterations

    def run(self, objective: str, evidence_provider: Callable[[ImprovementCandidate], Mapping[str, object]]) -> tuple[DuelResult, ...]:
        if not objective.strip():
            raise ValueError("objective is required")
        results: list[DuelResult] = []
        evidence: Mapping[str, object] = {}
        for iteration in range(1, self.max_iterations + 1):
            candidate = self.creator.create(objective, evidence, iteration=iteration)
            measured = evidence_provider(candidate)
            evaluation = self.critic.evaluate(candidate, measured)
            next_instruction = (
                "Candidate passed evidence gates; submit it to the existing review/integration pipeline."
                if evaluation.passed
                else "Candidate did not pass; use Critic feedback to design the next bounded experiment."
            )
            results.append(DuelResult(candidate, evaluation, next_instruction))
            if evaluation.passed:
                break
            evidence = {"critic_feedback": evaluation.feedback, **dict(measured)}
        return tuple(results)


def _evidence_metrics(evidence: Mapping[str, object]) -> dict[str, float]:
    """Normalize objective evidence; missing metrics fail closed."""
    metrics = {}
    for name in ("accuracy", "stability", "efficiency", "safety"):
        value = evidence.get(name, 0.0)
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        metrics[name] = min(1.0, max(0.0, number))
    return metrics


__all__ = [
    "CriticAgent",
    "CriticEvaluation",
    "CreatorAgent",
    "CreatorCriticLoop",
    "DuelResult",
    "ImprovementCandidate",
]
