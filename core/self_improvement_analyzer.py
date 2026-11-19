"""Deterministic pattern analysis for persisted self-improvement signals.

This layer only analyzes validated history. It performs no model calls, file
mutation, repository writes, or automatic execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .self_improvement import ImprovementSignal


@dataclass(frozen=True)
class ImprovementPattern:
    key: str
    count: int
    signal_kinds: tuple[str, ...]
    task_ids: tuple[str, ...]
    example_detail: str


@dataclass(frozen=True)
class ImprovementAnalysis:
    total_signals: int
    failure_count: int
    repair_count: int
    recurring_patterns: tuple[ImprovementPattern, ...]

    @property
    def has_recurring_pattern(self) -> bool:
        return bool(self.recurring_patterns)


def _normalize_detail(detail: str) -> str:
    """Reduce volatile values so equivalent failures group together."""
    value = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", detail.casefold())
    value = re.sub(r"\b\d+\b", "<n>", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:240]


def analyze_signals(
    signals: tuple[ImprovementSignal, ...] | list[ImprovementSignal],
    *,
    min_occurrences: int = 2,
    max_patterns: int = 5,
) -> ImprovementAnalysis:
    """Return bounded recurring failure/repair patterns deterministically."""
    if min_occurrences < 1:
        raise ValueError("min_occurrences must be >= 1")
    if max_patterns < 1:
        raise ValueError("max_patterns must be >= 1")

    items = tuple(signals)
    failures = sum(signal.kind == "failure" for signal in items)
    repairs = sum(signal.kind == "repair" for signal in items)

    grouped: dict[str, list[ImprovementSignal]] = {}
    for signal in items:
        if signal.kind not in {"failure", "repair"}:
            continue
        key = _normalize_detail(signal.detail)
        if not key:
            continue
        grouped.setdefault(key, []).append(signal)

    ranked = sorted(
        grouped.items(),
        key=lambda item: (-len(item[1]), item[0]),
    )
    patterns: list[ImprovementPattern] = []
    for key, members in ranked:
        if len(members) < min_occurrences:
            continue
        patterns.append(
            ImprovementPattern(
                key=key,
                count=len(members),
                signal_kinds=tuple(sorted({item.kind for item in members})),
                task_ids=tuple(
                    dict.fromkeys(item.task_id for item in members if item.task_id)
                ),
                example_detail=members[-1].detail,
            )
        )
        if len(patterns) >= max_patterns:
            break

    return ImprovementAnalysis(
        total_signals=len(items),
        failure_count=failures,
        repair_count=repairs,
        recurring_patterns=tuple(patterns),
    )


__all__ = ["ImprovementAnalysis", "ImprovementPattern", "analyze_signals"]
