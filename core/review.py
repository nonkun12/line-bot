"""Channel-independent contract for competing AI review stages.

The module deliberately contains no model/vendor calls. A caller can plug in
local or free-tier models later while keeping review orchestration testable.
"""

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence


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


class AICompetitionLoop:
    """Run independent reviewers and require every gate to pass."""

    def __init__(self, reviewers: Mapping[str, Callable[[str], ReviewResult]]):
        self._reviewers = dict(reviewers)

    def review(self, artifact: str) -> ReviewDecision:
        if not isinstance(artifact, str) or not artifact.strip():
            raise ValueError("artifact is required")
        if not self._reviewers:
            raise ValueError("at least one reviewer is required")

        results = []
        for name, reviewer in self._reviewers.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("reviewer name is required")
            if not callable(reviewer):
                raise TypeError("reviewer must be callable")
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
