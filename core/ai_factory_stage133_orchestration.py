"""Wire local proposal models and independent verification into the AI Factory.

This composition root connects Stage 132 local clients to Stage 131's end-to-end
factory. TEST/REVIEW remain separately injected; generated artifacts remain
inert and human approval is still required for registration/activation.
"""
from __future__ import annotations

from dataclasses import dataclass

from .agent_collaboration_pipeline import CollaborationRoles, CollaborationStage
from .agent_factory import AgentBuilder, AgentFactory, AgentReviewer, AgentSandbox
from .ai_factory_orchestrator import AIFactoryOrchestrator
from .ai_factory_stage131_adapters import (
    RoleEvidenceProducer,
    Stage121FactoryAdapter,
    Stage123EvidenceRunner,
    Stage131AIFactory,
)
from .ai_factory_stage132_local_models import (
    LocalModelConfig,
    LocalModelRoleProducer,
    OllamaCapabilityGapDesigner,
    OllamaLoopbackClient,
    TrustedStageGate,
    build_stage132_producers,
)
from .capability_gap_discovery import CapabilityGapArchitect


@dataclass(frozen=True)
class Stage133ModelConfigs:
    """Distinct local model configurations for architect and builder roles."""

    designer: LocalModelConfig
    architect_role: LocalModelConfig
    builder_role: LocalModelConfig


@dataclass(frozen=True)
class Stage133Runtime:
    """Fully wired proposal runtime; no scheduler or activation side effects."""

    factory: Stage131AIFactory
    roles: CollaborationRoles
    local_role_producer: LocalModelRoleProducer

    def propose(self, gap):
        """Run one capability gap through the complete four-role pipeline."""
        return self.factory.propose(gap)


def build_stage133_runtime(
    *,
    configs: Stage133ModelConfigs,
    roles: CollaborationRoles,
    builder: AgentBuilder,
    sandbox: AgentSandbox,
    reviewer: AgentReviewer,
    test_gate: TrustedStageGate,
    review_gate: TrustedStageGate,
) -> Stage133Runtime:
    """Build the connected local-model -> collaboration -> candidate pipeline.

    Model calls are limited to loopback Ollama endpoints. DESIGN/BUILD use
    separate clients; TEST/REVIEW are independent injected evidence gates.
    The AgentFactory's own sandbox and reviewer are also required and run
    before a candidate can be returned.
    """
    role_producer = LocalModelRoleProducer(
        clients_by_stage={
            # Separate instances and model configs prevent role aliasing.
            CollaborationStage.DESIGN:
                OllamaLoopbackClient(configs.architect_role),
            CollaborationStage.BUILD:
                OllamaLoopbackClient(configs.builder_role),
        },
        role_by_stage={
            __import__("core.agent_collaboration_pipeline", fromlist=["CollaborationStage"]).CollaborationStage.DESIGN: roles.architect,
            __import__("core.agent_collaboration_pipeline", fromlist=["CollaborationStage"]).CollaborationStage.BUILD: roles.builder,
        },
    )
    producers = build_stage132_producers(
        local_model=role_producer,
        test_gate=test_gate,
        review_gate=review_gate,
    )
    gap_architect = CapabilityGapArchitect(
        OllamaCapabilityGapDesigner(OllamaLoopbackClient(configs.designer))
    )
    agent_factory = AgentFactory(
        architect=gap_architect,
        builder=builder,
        sandbox=sandbox,
        reviewer=reviewer,
        # No tools, resource scopes, or approval gate are implicitly granted.
        permitted_tools=(),
        permitted_resource_scopes=(),
        approval_gate=None,
    )
    factory_adapter = Stage121FactoryAdapter(
        factory=agent_factory,
        gap_architect=gap_architect,
    )
    collaboration = Stage123EvidenceRunner(roles=roles, producers=producers)
    orchestrator = AIFactoryOrchestrator(
        collaboration=collaboration,
        factory=factory_adapter,
    )
    integrated = Stage131AIFactory(
        gap_architect=gap_architect,
        factory_adapter=factory_adapter,
        collaboration=collaboration,
        orchestrator=orchestrator,
    )
    return Stage133Runtime(
        factory=integrated,
        roles=roles,
        local_role_producer=role_producer,
    )


__all__ = ["Stage133ModelConfigs", "Stage133Runtime", "build_stage133_runtime"]
