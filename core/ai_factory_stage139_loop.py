"""Bounded AI Factory loop: process supplied gaps and file pending candidates."""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Callable, Protocol, Sequence
from .agent_factory import AgentCreationRecord
from .ai_factory_orchestrator import (
    AIFactoryOrchestrator, CapabilityGapRequest, LoopSafety, LoopTickReport,
    OrchestrationResult, FactoryStage,
)
from .ai_factory_stage138_catalog import PendingAgentCatalog, PendingAgentCandidate


class CandidateLookup(Protocol):
    def __call__(self, agent_name: str) -> AgentCreationRecord | None: ...


@dataclass(frozen=True)
class Stage139Report:
    tick: LoopTickReport
    pending_candidates: tuple[PendingAgentCandidate, ...]
    catalog_failures: tuple[str, ...] = ()


class Stage139LoopController:
    """Wrap the existing bounded orchestrator with the pending-only catalog."""
    def __init__(
        self,
        *,
        orchestrator: AIFactoryOrchestrator,
        catalog: PendingAgentCatalog,
        candidate_lookup: CandidateLookup,
    ) -> None:
        self.orchestrator = orchestrator
        self.catalog = catalog
        self.candidate_lookup = candidate_lookup

    def run_tick(
        self,
        tick_id: str,
        gaps: Sequence[CapabilityGapRequest],
        *,
        safety: LoopSafety = LoopSafety(),
    ) -> Stage139Report:
        # Repeat safety checks at this boundary before any orchestrator/model call.
        if safety.kill_switch_active:
            return Stage139Report(LoopTickReport(tick_id, (), "global kill switch is active"), ())
        if safety.hold_active:
            return Stage139Report(LoopTickReport(tick_id, (), "HOLD is active"), ())
        if not safety.evidence_complete:
            return Stage139Report(LoopTickReport(tick_id, (), "required evidence is incomplete"), ())
        if not safety.budget_available:
            return Stage139Report(LoopTickReport(tick_id, (), "safe execution budget is unavailable"), ())
        if not 1 <= safety.max_candidates_per_tick <= 4:
            return Stage139Report(LoopTickReport(tick_id, (), "max_candidates_per_tick must be between 1 and 4"), ())
        raw = self.orchestrator.run_tick(tick_id, gaps, safety=safety)
        pending: list[PendingAgentCandidate] = []
        failures: list[str] = []
        results: list[OrchestrationResult] = []
        for result in raw.processed:
            if result.candidate is None:
                results.append(result)
                continue
            try:
                record = self.candidate_lookup(result.candidate.agent_name)
                if record is None:
                    raise LookupError("reviewed AgentCreationRecord is unavailable")
                candidate = self.catalog.submit(record)
                pending.append(candidate)
                results.append(result)
            except Exception as exc:
                reason = f"pending catalog rejected candidate: {type(exc).__name__}: {exc}"
                failures.append(f"{result.gap_id}: {reason}")
                results.append(replace(result, candidate=None, blocked_reason=reason))
        return Stage139Report(
            tick=LoopTickReport(raw.tick_id, tuple(results), raw.stopped_reason),
            pending_candidates=tuple(pending),
            catalog_failures=tuple(failures),
        )


__all__ = ["Stage139Report", "Stage139LoopController"]
