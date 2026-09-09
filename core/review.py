"""Channel-independent contracts for competing AI review stages."""

from dataclasses import dataclass, field
from typing import Callable, Mapping


@dataclass(frozen=True)
class ReviewFinding:
    category: str
    severity: str
    message: str


@dataclass(frozen=True)
class ReviewResult:
    reviewer: str
    passed: bool
    findings: tuple[ReviewFinding, ...] = field(default_factory=tuple)
    score: float = 0.0


@dataclass(frozen=True)
class ReviewDecision:
    passed: bool
    score: float
    findings: tuple[ReviewFinding, ...] = field(default_factory=tuple)


class ReviewerRegistry:
    """Register named reviewers without coupling the core to model vendors."""

    def __init__(self, reviewers: Mapping[str, Callable[[str], ReviewResult]] | None = None):
        self._reviewers: dict[str, Callable[[str], ReviewResult]] = {}
        for name, reviewer in (reviewers or {}).items():
            self.register(name, reviewer)

    def register(self, name: str, reviewer: Callable[[str], ReviewResult]) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("reviewer name is required")
        if not callable(reviewer):
            raise TypeError("reviewer must be callable")
        if name in self._reviewers:
            raise ValueError(f"reviewer already registered: {name}")
        self._reviewers[name] = reviewer

    def get(self, name: str) -> Callable[[str], ReviewResult]:
        try:
            return self._reviewers[name]
        except KeyError as exc:
            raise KeyError(f"unknown reviewer: {name}") from exc

    def items(self) -> tuple[tuple[str, Callable[[str], ReviewResult]], ...]:
        return tuple(self._reviewers.items())

    def names(self) -> tuple[str, ...]:
        return tuple(self._reviewers)


class AICompetitionLoop:
    """Run independent reviewers and require every gate to pass."""

    def __init__(self, reviewers: Mapping[str, Callable[[str], ReviewResult]] | ReviewerRegistry):
        if isinstance(reviewers, ReviewerRegistry):
            self._reviewers = reviewers
        else:
            self._reviewers = ReviewerRegistry(reviewers)

    @property
    def reviewers(self) -> ReviewerRegistry:
        return self._reviewers

    def review(self, artifact: str) -> ReviewDecision:
        if not isinstance(artifact, str) or not artifact.strip():
            raise ValueError("artifact is required")
        items = self._reviewers.items()
        if not items:
            raise ValueError("at least one reviewer is required")

        results = []
        for _, reviewer in items:
            result = reviewer(artifact)
            if not isinstance(result, ReviewResult):
                raise TypeError("reviewer must return ReviewResult")
            results.append(result)

        findings = tuple(
            finding for result in results for finding in result.findings
        )
        score = sum(float(result.score) for result in results) / len(results)
        passed = all(result.passed for result in results)
        return ReviewDecision(passed=passed, score=score, findings=findings)
