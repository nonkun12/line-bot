"""Evidence-based feedback for choosing idea-generation strategies.

Only measured experiment outcomes affect ranking. Review opinions and
unverified claims are intentionally excluded from the learning signal.
This module is deterministic, bounded, and has no persistence or execution side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt
from typing import Iterable

_MAX_EVIDENCE_CHARS = 300
_VALID_RESULTS = frozenset({"success", "failure", "unverified"})


@dataclass(frozen=True)
class IdeaOutcome:
    style: str
    result: str
    evidence: str

    def __post_init__(self) -> None:
        if not isinstance(self.style, str) or not self.style.strip() or len(self.style) > 64:
            raise ValueError("style must be a non-empty string <= 64 characters")
        if self.result not in _VALID_RESULTS:
            raise ValueError("result must be success, failure, or unverified")
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise ValueError("evidence is required")
        if len(self.evidence) > _MAX_EVIDENCE_CHARS:
            raise ValueError("evidence exceeds 300 characters")


def rank_idea_styles(
    styles: Iterable[str],
    outcomes: Iterable[IdeaOutcome] = (),
) -> tuple[str, ...]:
    """Rank styles using bounded UCB1 exploration over verified experiments.

    Unverified results are ignored. Original style order is the deterministic
    tie-breaker. A style with little evidence receives an exploration bonus.
    """
    ordered = tuple(dict.fromkeys(styles))
    if any(not isinstance(style, str) or not style.strip() for style in ordered):
        raise ValueError("styles must be non-empty strings")
    if not ordered:
        return ()

    stats = {style: [0, 0] for style in ordered}  # successes, trials
    for outcome in tuple(outcomes)[-500:]:
        if not isinstance(outcome, IdeaOutcome):
            raise TypeError("outcomes must contain IdeaOutcome values")
        if outcome.style not in stats or outcome.result == "unverified":
            continue
        stats[outcome.style][1] += 1
        if outcome.result == "success":
            stats[outcome.style][0] += 1

    total_trials = sum(trials for _, trials in stats.values())
    if total_trials == 0:
        return ordered

    def score(style: str) -> float:
        successes, trials = stats[style]
        if trials == 0:
            return float("inf")
        mean = successes / trials
        exploration = sqrt(2.0 * log(total_trials + 1) / trials)
        return mean + exploration

    indexed = list(enumerate(ordered))
    indexed.sort(key=lambda item: (-score(item[1]), item[0]))
    return tuple(style for _, style in indexed)


__all__ = ["IdeaOutcome", "rank_idea_styles"]
