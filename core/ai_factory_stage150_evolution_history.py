"""Stage 150: multi-generation evolution history and health diagnostics.

Consumes only Stage 149's authenticated, immutable population snapshots.
This bounded in-memory ledger detects improvement, stagnation and regression;
it does not persist, execute models, merge weights or advance generations.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from threading import RLock
from typing import Sequence

from .ai_factory_stage141_evolution import Fitness, dominates
from .ai_factory_stage149_evolutionary_selection import EvolutionPopulationSnapshot


class EvolutionHistoryError(ValueError):
    """Raised when generation history is incomplete or inconsistent."""


class EvolutionTrend(str, Enum):
    IMPROVING = "improving"
    STAGNANT = "stagnant"
    REGRESSING = "regressing"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class GenerationObservation:
    generation: int
    candidate_ids: tuple[str, ...]
    fitnesses: tuple[Fitness, ...]
    evidence_digests: tuple[str, ...]
    evaluation_suite_digest: str


@dataclass(frozen=True)
class EvolutionHealthReport:
    observed_generations: tuple[int, ...]
    trend: EvolutionTrend
    improvement_events: int
    regression_events: int
    current_stagnation_streak: int
    stagnation_window: int
    stagnation_alert: bool
    regression_alert: bool
    comparable_suite_digest: str
    auto_advance: bool = False
    merge_authorized: bool = False
    activation_authorized: bool = False
    production_switch_authorized: bool = False


def _compare(current: Sequence[Fitness], previous: Sequence[Fitness]) -> EvolutionTrend:
    improved = any(dominates(now, before) for now in current for before in previous)
    regressed = bool(current) and all(
        any(dominates(before, now) for before in previous) for now in current
    )
    if improved and not regressed:
        return EvolutionTrend.IMPROVING
    if regressed and not improved:
        return EvolutionTrend.REGRESSING
    return EvolutionTrend.STAGNANT


class EvolutionHistoryLedger:
    """Bounded append-only in-memory history for independently evaluated generations."""

    def __init__(self, *, max_generations: int = 256) -> None:
        if not isinstance(max_generations, int) or isinstance(max_generations, bool) or not 2 <= max_generations <= 10_000:
            raise ValueError("max_generations must be between 2 and 10000")
        self._max_generations = max_generations
        self._observations: list[GenerationObservation] = []
        self._suite_digest: str | None = None
        self._lock = RLock()

    def record_snapshot(self, snapshot: EvolutionPopulationSnapshot) -> tuple[GenerationObservation, ...]:
        """Record previously authenticated Stage 149 entries, once per generation."""
        if not isinstance(snapshot, EvolutionPopulationSnapshot):
            raise EvolutionHistoryError("a typed Stage 149 population snapshot is required")
        if not snapshot.entries:
            raise EvolutionHistoryError("empty population snapshots cannot establish evolution history")
        grouped: dict[int, list] = {}
        for entry in snapshot.entries:
            if entry.enabled or entry.status != "pending_human_approval":
                raise EvolutionHistoryError("history accepts only disabled, pending candidates")
            if not re.fullmatch(r"[0-9a-f]{64}", entry.evidence_digest):
                raise EvolutionHistoryError("candidate evidence digest must be a SHA-256 hex digest")
            if not re.fullmatch(r"[0-9a-f]{64}", entry.evaluation_suite_digest):
                raise EvolutionHistoryError("evaluation suite digest must be a SHA-256 hex digest")
            grouped.setdefault(entry.generation, []).append(entry)

        observations = tuple(
            GenerationObservation(
                generation=generation,
                candidate_ids=tuple(sorted(item.candidate_id for item in entries)),
                fitnesses=tuple(item.fitness for item in sorted(entries, key=lambda item: item.candidate_id)),
                evidence_digests=tuple(sorted(item.evidence_digest for item in entries)),
                evaluation_suite_digest=entries[0].evaluation_suite_digest,
            )
            for generation, entries in sorted(grouped.items())
        )
        if any(len(set(item.evaluation_suite_digest for item in grouped[generation])) != 1
               for generation in grouped):
            raise EvolutionHistoryError("a generation contains incomparable evaluation suites")
        if len({item.evaluation_suite_digest for item in observations}) != 1:
            raise EvolutionHistoryError("a snapshot mixes evaluation suites across generations")

        with self._lock:
            suite = observations[0].evaluation_suite_digest
            if self._suite_digest is not None and suite != self._suite_digest:
                raise EvolutionHistoryError("evaluation suite changed; start a separately versioned history")
            existing = {item.generation for item in self._observations}
            new = tuple(item for item in observations if item.generation not in existing)
            if any(item.generation in existing for item in observations):
                raise EvolutionHistoryError("generation history is append-only; duplicate generation rejected")
            if self._observations and new and new[0].generation <= self._observations[-1].generation:
                raise EvolutionHistoryError("generation numbers must increase monotonically")
            if len(self._observations) + len(new) > self._max_generations:
                raise EvolutionHistoryError("history capacity reached; recording is fail-closed")
            if new:
                self._suite_digest = suite
                self._observations.extend(new)
        return new

    def observations(self) -> tuple[GenerationObservation, ...]:
        with self._lock:
            return tuple(self._observations)

    def analyze(self, *, stagnation_window: int = 3) -> EvolutionHealthReport:
        if not isinstance(stagnation_window, int) or isinstance(stagnation_window, bool) or not 2 <= stagnation_window <= 100:
            raise ValueError("stagnation_window must be between 2 and 100")
        history = self.observations()
        if not history:
            return EvolutionHealthReport(
                (), EvolutionTrend.INSUFFICIENT_DATA, 0, 0, 0,
                stagnation_window, False, False, "",
            )
        if len(history) < 2:
            return EvolutionHealthReport(
                tuple(item.generation for item in history), EvolutionTrend.INSUFFICIENT_DATA,
                0, 0, 0, stagnation_window, False, False,
                history[0].evaluation_suite_digest,
            )

        trends = tuple(_compare(now.fitnesses, before.fitnesses)
                       for before, now in zip(history, history[1:]))
        improvements = sum(item is EvolutionTrend.IMPROVING for item in trends)
        regressions = sum(item is EvolutionTrend.REGRESSING for item in trends)
        streak = 0
        for item in reversed(trends):
            if item is EvolutionTrend.STAGNANT:
                streak += 1
            else:
                break
        latest = trends[-1]
        return EvolutionHealthReport(
            observed_generations=tuple(item.generation for item in history),
            trend=latest,
            improvement_events=improvements,
            regression_events=regressions,
            current_stagnation_streak=streak,
            stagnation_window=stagnation_window,
            stagnation_alert=streak >= stagnation_window,
            regression_alert=latest is EvolutionTrend.REGRESSING,
            comparable_suite_digest=history[0].evaluation_suite_digest,
        )


__all__ = [
    "EvolutionHistoryError", "EvolutionTrend", "GenerationObservation",
    "EvolutionHealthReport", "EvolutionHistoryLedger",
]
