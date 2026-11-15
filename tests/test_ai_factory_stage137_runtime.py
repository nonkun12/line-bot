import pytest
from core.agent_collaboration_pipeline import CollaborationRoles, CollaborationStage
from core.ai_factory_stage132_local_models import LocalModelConfig
from core.ai_factory_stage137_runtime import Stage137Config, build_stage137_runtime

class FakeClient:
    def __init__(self, config): self.config = config
    def chat(self, *, system, prompt): raise AssertionError("no model call expected in wiring test")

def config(reviewer="reviewer-model"):
    return Stage137Config(
        LocalModelConfig("designer-model"),
        LocalModelConfig("architect-model"),
        LocalModelConfig("builder-model"),
        LocalModelConfig(reviewer),
        "python:3.13-slim@sha256:" + "a" * 64,
    )

def roles():
    return CollaborationRoles("architect", "builder", "tester", "reviewer")

def _test_gate(gap, stage):
    from core.ai_factory_stage131_adapters import RoleEvidenceInput
    return RoleEvidenceInput("tester", "tests", "passed", ("independent test",), passed=True)

def review_gate(gap, stage):
    from core.ai_factory_stage131_adapters import RoleEvidenceInput
    return RoleEvidenceInput("reviewer", "review", "approved", ("independent review",), approved=True)

def test_stage137_wires_concrete_builder_sandbox_and_independent_reviewer():
    clients = []
    def factory(cfg):
        client = FakeClient(cfg); clients.append(client); return client
    runtime = build_stage137_runtime(
        config=config(), roles=roles(), test_gate=_test_gate, review_gate=review_gate,
        sandbox_runner=lambda *a, **k: None, model_client_factory=factory,
    )
    factory = runtime.pipeline.factory.factory_adapter.factory
    assert factory.builder is runtime.builder
    assert factory.sandbox is runtime.sandbox
    assert factory.reviewer is runtime.reviewer
    assert runtime.builder.client is not runtime.reviewer.client
    assert len(clients) == 2

def test_stage137_rejects_same_builder_and_reviewer_model():
    with pytest.raises(ValueError, match="distinct model identities"):
        build_stage137_runtime(
            config=config("builder-model"), roles=roles(), test_gate=_test_gate, review_gate=review_gate,
            sandbox_runner=lambda *a, **k: None,
        )

def test_stage137_rejects_model_factory_returning_same_client():
    shared = FakeClient(None)
    with pytest.raises(ValueError, match="separate model client"):
        build_stage137_runtime(
            config=config(), roles=roles(), test_gate=_test_gate, review_gate=review_gate,
            sandbox_runner=lambda *a, **k: None, model_client_factory=lambda cfg: shared,
        )

def test_stage137_has_no_implicit_permission_or_approval_grants():
    runtime = build_stage137_runtime(
        config=config(), roles=roles(), test_gate=_test_gate, review_gate=review_gate,
        sandbox_runner=lambda *a, **k: None, model_client_factory=FakeClient,
    )
    factory = runtime.pipeline.factory.factory_adapter.factory
    assert factory.permitted_tools == frozenset()
    assert factory.permitted_resource_scopes == frozenset()
    assert factory.approval_gate is None
