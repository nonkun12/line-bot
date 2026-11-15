"""Wire local Builder, disposable sandbox and independent Reviewer end to end."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

from .agent_collaboration_pipeline import CollaborationRoles
from .ai_factory_stage132_local_models import LocalModelConfig, OllamaLoopbackClient
from .ai_factory_stage133_orchestration import (
    Stage133ModelConfigs, Stage133Runtime, build_stage133_runtime,
)
from .ai_factory_stage134_builder import OllamaAgentBuilder
from .ai_factory_stage135_sandbox import DockerSandbox, ProcessRunner
from .ai_factory_stage136_reviewer import OllamaAgentReviewer, ReviewModelClient
from .ai_factory_stage132_local_models import TrustedStageGate


@dataclass(frozen=True)
class Stage137Config:
    designer: LocalModelConfig
    architect_role: LocalModelConfig
    builder_role: LocalModelConfig
    reviewer: LocalModelConfig
    sandbox_image: str
    sandbox_timeout_seconds: int = 45


@dataclass(frozen=True)
class Stage137Runtime:
    pipeline: Stage133Runtime
    builder: OllamaAgentBuilder
    sandbox: DockerSandbox
    reviewer: OllamaAgentReviewer

    def propose(self, gap):
        return self.pipeline.propose(gap)


def build_stage137_runtime(
    *,
    config: Stage137Config,
    roles: CollaborationRoles,
    test_gate: TrustedStageGate,
    review_gate: TrustedStageGate,
    sandbox_runner: ProcessRunner,
    model_client_factory: Callable[[LocalModelConfig], ReviewModelClient] = OllamaLoopbackClient,
) -> Stage137Runtime:
    """Compose DESIGN/BUILD role models, code Builder, sandbox and Reviewer."""
    model_names = {
        config.designer.model,
        config.architect_role.model,
        config.builder_role.model,
        config.reviewer.model,
    }
    if len(model_names) != 4:
        raise ValueError("designer, architect, builder and reviewer must use distinct model identities")
    builder_client = model_client_factory(config.builder_role)
    reviewer_client = model_client_factory(config.reviewer)
    if builder_client is reviewer_client:
        raise ValueError("builder and reviewer must use separate model client instances")
    builder = OllamaAgentBuilder(builder_client)
    sandbox = DockerSandbox(
        image=config.sandbox_image,
        timeout_seconds=config.sandbox_timeout_seconds,
        runner=sandbox_runner,
    )
    reviewer = OllamaAgentReviewer(reviewer_client)
    pipeline = build_stage133_runtime(
        configs=Stage133ModelConfigs(
            designer=config.designer,
            architect_role=config.architect_role,
            builder_role=config.builder_role,
        ),
        roles=roles,
        builder=builder,
        sandbox=sandbox,
        reviewer=reviewer,
        test_gate=test_gate,
        review_gate=review_gate,
    )
    if pipeline.factory.factory_adapter.factory.builder is not builder:
        raise RuntimeError("Builder wiring verification failed")
    if pipeline.factory.factory_adapter.factory.sandbox is not sandbox:
        raise RuntimeError("sandbox wiring verification failed")
    if pipeline.factory.factory_adapter.factory.reviewer is not reviewer:
        raise RuntimeError("Reviewer wiring verification failed")
    return Stage137Runtime(pipeline, builder, sandbox, reviewer)


__all__ = ["Stage137Config", "Stage137Runtime", "build_stage137_runtime"]
