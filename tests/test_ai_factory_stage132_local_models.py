import json
from types import SimpleNamespace

import pytest

from core.agent_collaboration_pipeline import CollaborationStage
from core.agent_specs import AgentLifecycle
from core.ai_factory_stage132_local_models import (
    LocalModelConfig,
    LocalModelRoleProducer,
    OllamaCapabilityGapDesigner,
    build_stage132_producers,
)


class FakeClient:
    config = SimpleNamespace(model="test-local-model")

    def __init__(self, content="proposal"):
        self.content = content
        self.calls = []

    def chat(self, *, system, prompt):
        self.calls.append((system, prompt))
        return self.content


def gap():
    return SimpleNamespace(
        capability="repository-auditing",
        description="Audit repository changes",
        evidence=("no enabled auditor",),
        requirement=SimpleNamespace(description="Audit repository changes"),
    )


def test_local_model_config_accepts_loopback_only():
    assert LocalModelConfig("lfm3:1.7b-q4_0").base_url == "http://127.0.0.1:11434"
    assert LocalModelConfig("bonsai-9b", "http://localhost:11434")


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:11434",
    "http://192.168.1.10:11434",
    "http://example.com:11434",
    "http://user:pass@127.0.0.1:11434",
    "http://127.0.0.1:11434/api",
    "http://127.0.0.1:11434?proxy=1",
])
def test_local_model_config_rejects_non_loopback_or_ambiguous_urls(url):
    with pytest.raises(ValueError):
        LocalModelConfig("model", url)


def test_local_model_config_supports_explicit_thinking_control():
    assert LocalModelConfig("lfm3", think=False).think is False
    assert LocalModelConfig("lfm3", think=True).think is True
    with pytest.raises(ValueError, match="think must"):
        LocalModelConfig("lfm3", think="false")


def test_local_model_config_bounds_timeout_and_output():
    with pytest.raises(ValueError):
        LocalModelConfig("model", timeout_seconds=90)
    with pytest.raises(ValueError):
        LocalModelConfig("model", max_output_tokens=99999)


def test_role_producer_generates_design_and_build_only():
    design_client = FakeClient()
    build_client = FakeClient()
    producer = LocalModelRoleProducer(
        clients_by_stage={
            CollaborationStage.DESIGN: design_client,
            CollaborationStage.BUILD: build_client,
        },
        role_by_stage={
            CollaborationStage.DESIGN: "architect-ai",
            CollaborationStage.BUILD: "builder-ai",
        },
    )
    design = producer(gap(), CollaborationStage.DESIGN)
    build = producer(gap(), CollaborationStage.BUILD)
    assert design.agent == "architect-ai"
    assert build.agent == "builder-ai"
    assert design.passed is None and design.approved is None
    assert build.passed is None and build.approved is None
    assert len(design_client.calls) == 1
    assert len(build_client.calls) == 1


def test_design_and_build_require_distinct_model_clients():
    shared = FakeClient()
    with pytest.raises(ValueError, match="separate model client"):
        LocalModelRoleProducer(
            clients_by_stage={
                CollaborationStage.DESIGN: shared,
                CollaborationStage.BUILD: shared,
            },
            role_by_stage={
                CollaborationStage.DESIGN: "architect-ai",
                CollaborationStage.BUILD: "builder-ai",
            },
        )


@pytest.mark.parametrize("stage", [CollaborationStage.TEST, CollaborationStage.REVIEW])
def test_role_producer_cannot_self_certify_gates(stage):
    producer = LocalModelRoleProducer(
        clients_by_stage={
            CollaborationStage.DESIGN: FakeClient(),
            CollaborationStage.BUILD: FakeClient(),
        },
        role_by_stage={
            CollaborationStage.DESIGN: "architect-ai",
            CollaborationStage.BUILD: "builder-ai",
        },
    )
    with pytest.raises(PermissionError, match="cannot produce"):
        producer(gap(), stage)


def test_producer_map_requires_independent_test_and_review_gates():
    producer = LocalModelRoleProducer(
        clients_by_stage={
            CollaborationStage.DESIGN: FakeClient(),
            CollaborationStage.BUILD: FakeClient(),
        },
        role_by_stage={
            CollaborationStage.DESIGN: "architect-ai",
            CollaborationStage.BUILD: "builder-ai",
        },
    )
    with pytest.raises(ValueError, match="independent"):
        build_stage132_producers(local_model=producer, test_gate=None, review_gate=lambda *_: None)
    gates = build_stage132_producers(
        local_model=producer,
        test_gate=lambda *_: None,
        review_gate=lambda *_: None,
    )
    assert set(gates) == {
        CollaborationStage.DESIGN,
        CollaborationStage.BUILD,
        CollaborationStage.TEST,
        CollaborationStage.REVIEW,
    }
    assert gates[CollaborationStage.TEST] is not producer
    assert gates[CollaborationStage.REVIEW] is not producer


def test_local_model_cannot_be_reused_as_test_or_review_gate():
    producer = LocalModelRoleProducer(
        clients_by_stage={
            CollaborationStage.DESIGN: FakeClient(),
            CollaborationStage.BUILD: FakeClient(),
        },
        role_by_stage={
            CollaborationStage.DESIGN: "architect-ai",
            CollaborationStage.BUILD: "builder-ai",
        },
    )
    with pytest.raises(ValueError, match="cannot be reused"):
        build_stage132_producers(local_model=producer, test_gate=producer, review_gate=lambda *_: None)


def test_designer_creates_inert_generated_spec_from_strict_json():
    payload = {
        "name": "repository-auditor",
        "purpose": "Audit repository changes",
        "input_contract": "Diff and test evidence",
        "output_contract": "Findings with source references",
        "tests": ["reject_missing_diff", "report_unverified_claims"],
    }
    designer = OllamaCapabilityGapDesigner(FakeClient(json.dumps(payload)))
    spec = designer.design(gap())
    assert spec.lifecycle is AgentLifecycle.GENERATED
    assert spec.allowed_tools == ()
    assert spec.resource_scope == ()
    assert spec.metadata["designer"] == "ollama-loopback"
    assert spec.validate() == ()


def test_designer_rejects_model_requested_tools_and_extra_fields():
    payload = {
        "name": "unsafe-agent",
        "purpose": "Do things",
        "input_contract": "Input",
        "output_contract": "Output",
        "tests": ["test"],
        "allowed_tools": ["shell"],
    }
    designer = OllamaCapabilityGapDesigner(FakeClient(json.dumps(payload)))
    with pytest.raises(ValueError, match="schema"):
        designer.design(gap())


def test_designer_rejects_invalid_json_and_names():
    with pytest.raises(ValueError, match="strict JSON"):
        OllamaCapabilityGapDesigner(FakeClient("not json")).design(gap())
    payload = {
        "name": "Root Agent",
        "purpose": "Purpose",
        "input_contract": "Input",
        "output_contract": "Output",
        "tests": ["test"],
    }
    with pytest.raises(ValueError, match="kebab-case"):
        OllamaCapabilityGapDesigner(FakeClient(json.dumps(payload))).design(gap())


def test_designer_rejects_missing_tests():
    payload = {
        "name": "empty-tests",
        "purpose": "Purpose",
        "input_contract": "Input",
        "output_contract": "Output",
        "tests": [],
    }
    with pytest.raises(ValueError, match="validation tests"):
        OllamaCapabilityGapDesigner(FakeClient(json.dumps(payload))).design(gap())
