from core.agent_specs import AgentLifecycle
from core.distributed_execution_artifact import ExecutionArtifact, StaticExecutionArtifactProvider
from core.distributed_agent_bridge import build_agent_registry
from core.distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG
from core.distributed_agent_versions import (
    DistributedAgentVersion,
    DistributedAgentVersionRegistry,
    catalog_digest,
)
from core.distributed_execution_gate import DistributedExecutionGateError, ExecutionIdentity
from core.multi_agent import AgentRole, AgentTask


FULL_SHA = "a" * 40


class FakeAgent:
    name = "ai_news"
    enabled = True

    def can_handle(self, request):
        return request.message == "AI NEWSをテスト"

    def handle(self, request):
        class Response:
            text = "news-ready"
        return Response()


def _execution_context():
    descriptor = next(item for item in DISTRIBUTED_AGENT_CATALOG if item.key == "ai_news")
    digest = catalog_digest(descriptor)
    version = DistributedAgentVersion(
        agent_key="ai_news",
        version="0.2.0",
        lifecycle=AgentLifecycle.ENABLED,
        git_sha=FULL_SHA,
        catalog_digest=digest,
    )
    registry = DistributedAgentVersionRegistry([version])
    artifact = ExecutionArtifact(
        identity=ExecutionIdentity("ai_news", "0.2.0", FULL_SHA, digest),
        artifact_id="test-ai-news",
    )
    return registry, StaticExecutionArtifactProvider((artifact,))


def test_bridge_registers_explicit_news_executor():
    class Registry:
        def get(self, name):
            if name == "ai_news":
                return FakeAgent()
            return None

    version_registry, artifact_provider = _execution_context()
    executors = build_agent_registry(
        Registry(),
        version_registry=version_registry,
        artifact_provider=artifact_provider,
    ).build()
    assert AgentRole.NEWS in executors
    result = executors[AgentRole.NEWS].execute(
        AgentTask(
            task_id="req-1",
            role=AgentRole.NEWS,
            instruction="AI NEWSをテスト",
        )
    )
    assert result.success is True
    assert result.summary == "news-ready"


def test_bridge_rejects_identity_mismatch_before_agent_handle():
    calls = []

    class GuardedAgent(FakeAgent):
        def handle(self, request):
            calls.append("handle")
            return super().handle(request)

    class Registry:
        def get(self, name):
            if name == "ai_news":
                return GuardedAgent()
            return None

    version_registry, artifact_provider = _execution_context()
    wrong = ExecutionArtifact(
        identity=ExecutionIdentity(
            "ai_news",
            "0.2.1",
            FULL_SHA,
            artifact_provider.get("ai_news").identity.catalog_digest,
        ),
        artifact_id="wrong-version",
    )
    bad_provider = StaticExecutionArtifactProvider((wrong,))
    executors = build_agent_registry(
        Registry(),
        version_registry=version_registry,
        artifact_provider=bad_provider,
    ).build()

    import pytest

    with pytest.raises(DistributedExecutionGateError):
        executors[AgentRole.NEWS].execute(
            AgentTask(task_id="req-2", role=AgentRole.NEWS, instruction="AI NEWSをテスト")
        )

    assert calls == []
