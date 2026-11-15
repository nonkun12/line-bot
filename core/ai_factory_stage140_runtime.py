"""Stage 140 end-to-end self-expanding AI Factory entry point.

It discovers explicit capability gaps, binds their evidence, runs the bounded
multi-agent factory and records successful candidates in a pending-only catalog.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from .agent_collaboration_pipeline import CollaborationRoles
from .ai_factory_orchestrator import CapabilityGapRequest, LoopSafety, LoopTickReport
from .ai_factory_stage137_runtime import Stage137Config, Stage137Runtime, build_stage137_runtime
from .ai_factory_stage138_catalog import PendingAgentCatalog, PendingAgentCandidate
from .ai_factory_stage139_loop import Stage139LoopController, Stage139Report
from .ai_factory_stage132_local_models import TrustedStageGate
from .ai_factory_stage137_runtime import ReviewModelClient
from .ai_factory_stage135_sandbox import ProcessRunner
from .ai_factory_stage132_local_models import LocalModelConfig
from .capability_gap_discovery import (
    AgentCapabilityInventory, CapabilityGapPlanner, CapabilityGapReport,
    CapabilityRequirement,
)


@dataclass(frozen=True)
class Stage140Config:
    models: Stage137Config


@dataclass(frozen=True)
class Stage140CycleReport:
    tick_id: str
    discovery: CapabilityGapReport
    loop: Stage139Report

    @property
    def pending_count(self) -> int:
        return len(self.loop.pending_candidates)


@dataclass(frozen=True)
class Stage140Runtime:
    pipeline: Stage137Runtime
    catalog: PendingAgentCatalog
    controller: Stage139LoopController
    planner: CapabilityGapPlanner

    def run_cycle(
        self,
        tick_id: str,
        requirements: Sequence[CapabilityRequirement],
        inventory: AgentCapabilityInventory,
        *,
        safety: LoopSafety = LoopSafety(),
    ) -> Stage140CycleReport:
        discovery = self.planner.analyze(requirements, inventory)
        # Check stop conditions before binding gaps or invoking any model.
        stop_reason = None
        if safety.kill_switch_active: stop_reason = "global kill switch is active"
        elif safety.hold_active: stop_reason = "HOLD is active"
        elif not safety.evidence_complete: stop_reason = "required evidence is incomplete"
        elif not safety.budget_available: stop_reason = "safe execution budget is unavailable"
        elif not 1 <= safety.max_candidates_per_tick <= 4:
            stop_reason = "max_candidates_per_tick must be between 1 and 4"
        if stop_reason:
            return Stage140CycleReport(tick_id, discovery, Stage139Report(
                LoopTickReport(tick_id, (), stop_reason), ()))
        if not discovery.gaps:
            return Stage140CycleReport(tick_id, discovery, Stage139Report(
                LoopTickReport(tick_id, (), "no capability gaps detected"), ()))

        gap_architect = self.pipeline.pipeline.factory.gap_architect
        requests = []
        try:
            for gap in discovery.gaps:
                gap_architect.bind(gap)
                requests.append(CapabilityGapRequest(
                    gap_id=gap.gap_id,
                    capability=gap.capability,
                    description=gap.requirement.description,
                    evidence=tuple(gap.evidence),
                ))
        except Exception as exc:
            return Stage140CycleReport(tick_id, discovery, Stage139Report(
                LoopTickReport(tick_id, (), f"capability gap binding failed: {type(exc).__name__}: {exc}"), ()))
        result = self.controller.run_tick(tick_id, requests, safety=safety)
        return Stage140CycleReport(tick_id, discovery, result)


def build_stage140_runtime(
    *,
    config: Stage140Config,
    roles: CollaborationRoles,
    test_gate: TrustedStageGate,
    review_gate: TrustedStageGate,
    sandbox_runner: ProcessRunner,
    model_client_factory=None,
) -> Stage140Runtime:
    from .ai_factory_stage137_runtime import build_stage137_runtime
    kwargs = {}
    if model_client_factory is not None:
        kwargs["model_client_factory"] = model_client_factory
    pipeline = build_stage137_runtime(
        config=config.models,
        roles=roles,
        test_gate=test_gate,
        review_gate=review_gate,
        sandbox_runner=sandbox_runner,
        **kwargs,
    )
    catalog = PendingAgentCatalog()
    orchestrator = pipeline.pipeline.factory.orchestrator
    factory = pipeline.pipeline.factory.factory_adapter.factory
    controller = Stage139LoopController(
        orchestrator=orchestrator,
        catalog=catalog,
        candidate_lookup=factory.get_candidate,
    )
    return Stage140Runtime(
        pipeline=pipeline,
        catalog=catalog,
        controller=controller,
        planner=CapabilityGapPlanner(),
    )


__all__ = [
    "Stage140Config", "Stage140CycleReport", "Stage140Runtime", "build_stage140_runtime",
]
