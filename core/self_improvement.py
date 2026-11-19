"""Bounded, provider-neutral feedback loop for autonomous improvement.

This module deliberately separates *learning signals* from code changes. It can
observe development reports, classify recurring failures, and produce a small,
reviewable improvement task. Applying a proposal remains an explicit downstream
responsibility so a bad model response cannot mutate the repository by itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .agent_runtime import RuntimeReport
from .multi_agent import AgentRole, AgentTask


_MAX_SIGNAL_KIND_CHARS = 32
_MAX_SIGNAL_TASK_ID_CHARS = 200
_MAX_SIGNAL_DETAIL_CHARS = 2000
_MAX_PROPOSAL_TITLE_CHARS = 200
_MAX_PROPOSAL_RATIONALE_CHARS = 2000
_MAX_PROPOSAL_SIGNALS = 8
_MAX_ENGINE_SIGNALS = 200


@dataclass(frozen=True)
class ImprovementSignal:
    kind: str
    task_id: str | None
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("signal kind is required")
        if len(self.kind) > _MAX_SIGNAL_KIND_CHARS:
            raise ValueError("signal kind exceeds 32 characters")
        if self.task_id is not None:
            if not isinstance(self.task_id, str) or len(self.task_id) > _MAX_SIGNAL_TASK_ID_CHARS:
                raise ValueError("signal task_id exceeds 200 characters")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise ValueError("signal detail is required")
        if len(self.detail) > _MAX_SIGNAL_DETAIL_CHARS:
            raise ValueError("signal detail exceeds 2000 characters")


@dataclass(frozen=True)
class ImprovementProposal:
    title: str
    rationale: str
    signals: tuple[ImprovementSignal, ...] = ()
    task: AgentTask | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("proposal title is required")
        if len(self.title) > _MAX_PROPOSAL_TITLE_CHARS:
            raise ValueError("proposal title exceeds 200 characters")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("proposal rationale is required")
        if len(self.rationale) > _MAX_PROPOSAL_RATIONALE_CHARS:
            raise ValueError("proposal rationale exceeds 2000 characters")
        signals = tuple(self.signals)
        if len(signals) > _MAX_PROPOSAL_SIGNALS:
            raise ValueError("too many proposal signals (max 8)")
        if any(not isinstance(signal, ImprovementSignal) for signal in signals):
            raise TypeError("proposal signals must be ImprovementSignal")
        object.__setattr__(self, "signals", signals)


@dataclass
class SelfImprovementEngine:
    """Collect bounded signals and turn them into reviewable proposals."""

    max_signals: int = 50
    _signals: list[ImprovementSignal] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.max_signals < 1 or self.max_signals > _MAX_ENGINE_SIGNALS:
            raise ValueError("max_signals must be between 1 and 200")

    @property
    def signals(self) -> tuple[ImprovementSignal, ...]:
        return tuple(self._signals)

    def observe(self, report: RuntimeReport) -> tuple[ImprovementSignal, ...]:
        """Convert one bounded runtime report into durable-in-memory signals."""
        new: list[ImprovementSignal] = []
        if report.success and report.integration_ready:
            new.append(ImprovementSignal("success", None, "development reached the integration gate"))
        if report.repair_attempts:
            new.append(ImprovementSignal(
                "repair", report.failed_task_id,
                f"development required {report.repair_attempts} repair attempt(s)",
            ))
        if report.failed_task_id and report.error:
            detail = str(report.error).replace("\x00", "").strip()[:_MAX_SIGNAL_DETAIL_CHARS]
            if detail:
                new.append(ImprovementSignal("failure", report.failed_task_id, detail))
        for signal in new:
            self._signals.append(signal)
        if len(self._signals) > self.max_signals:
            del self._signals[:-self.max_signals]
        return tuple(new)

    def propose(self) -> ImprovementProposal | None:
        """Return one deterministic proposal from recent signals, if useful."""
        if not self._signals:
            return None
        failures = [s for s in self._signals if s.kind == "failure"]
        repairs = [s for s in self._signals if s.kind == "repair"]
        if failures:
            latest = failures[-1]
            task = AgentTask(
                task_id="self-improvement:failure-analysis",
                role=AgentRole.DEBUGGER,
                instruction=(
                    "Analyze the latest autonomous-development failure, identify a "
                    "reproducible root cause, and propose a minimal test-backed fix. "
                    "Do not modify protected configuration or secrets."
                ),
                resources=frozenset({latest.task_id or "runtime"}),
                priority=10,
            )
            return ImprovementProposal(
                title="Analyze latest autonomous-development failure",
                rationale=latest.detail,
                signals=(latest,),
                task=task,
            )
        if len(repairs) >= 2:
            return ImprovementProposal(
                title="Review recurring repair pattern",
                rationale="Multiple repair attempts were required; inspect the common failure pattern before adding new behavior.",
                signals=tuple(repairs[-2:]),
            )
        return None

    def clear(self) -> None:
        """Forget in-memory signals after an explicit persistence boundary."""
        self._signals.clear()


def summarize_signals(signals: Iterable[ImprovementSignal]) -> str:
    """Produce a compact, deterministic summary for a management agent."""
    items = tuple(signals)
    if not items:
        return "No improvement signals recorded."
    return "; ".join(f"{s.kind}:{s.task_id or '-'}:{s.detail}" for s in items[-10:])
