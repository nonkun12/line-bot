"""Channel-independent contract for competing AI review stages.

The module deliberately contains no model/vendor calls.  A caller can plug in
local or free-tier models later while keeping review orchestration testable.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class ReviewFinding:
    category: str
    severity: str
    message: str


@dataclass(frozen=True)
class ReviewResult:
    reviewer: str
    passed: bool
    findings: Sequence[ReviewFinding] = field(default_factory=tuple)
    score: float = 0.0


@dataclass(frozen=True)
class ReviewDecision:
    passed: bool
    score: float
    findings: Sequence[ReviewFinding] = field(default_factory=tuple)


class AICompetitionLoop:
    """Run independent reviewers and require every gate to pass."""

    def __init__(self, reviewers: Mapping[str, Callable[[str], ReviewResult]]):
        self._reviewers = dict(reviewers)

    def review(self, artifact: str) -> ReviewDecision:
        if not isinstance(artifact, str) or not artifact.strip():
            raise ValueError("artifact is required")
        if not self._reviewers:
            raise ValueError("at least one reviewer is required")

        results = [reviewer(artifact) for reviewer in self._reviewers.values()]
        for result in results:
            if not isinstance(result, ReviewResult):
                raise TypeError("reviewer must return ReviewResult")

        findings = tuple(
            finding for result in results for finding in result.findings
        )
        score = sum(result.score for result in results) / len(results)
        passed = all(result.passed for result in results)
        return ReviewDecision(passed=passed, score=score, findings=findings)
