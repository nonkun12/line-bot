"""Deterministic diversity and positive-impact checks for IDEA candidates.

This module does not select a winner. It preserves unusual candidates and only
flags duplicate-looking proposals for review. Low feasibility is never a
reason to discard a creative idea here.
"""
from __future__ import annotations

from dataclasses import dataclass
from .idea_ai import Idea


@dataclass(frozen=True)
class IdeaReview:
    idea_id: str
    duplicate_style: bool
    unconventional: bool
    positive_impact_present: bool


def review_ideas(ideas: tuple[Idea, ...]) -> tuple[IdeaReview, ...]:
    seen: set[str] = set()
    reviews: list[IdeaReview] = []
    for idea in ideas:
        duplicate = idea.style in seen
        seen.add(idea.style)
        reviews.append(IdeaReview(
            idea_id=idea.idea_id,
            duplicate_style=duplicate,
            unconventional=idea.novelty >= 4 or idea.style in {"reframe", "architecture-leap"},
            positive_impact_present=bool(idea.positive_impact.strip()),
        ))
    return tuple(reviews)


def preserve_unconventional(ideas: tuple[Idea, ...]) -> tuple[Idea, ...]:
    """Return candidates unchanged; this layer must not filter by feasibility."""
    return ideas


__all__ = ["IdeaReview", "review_ideas", "preserve_unconventional"]
