from types import SimpleNamespace

import pytest

from core.agent_collaboration_pipeline import CollaborationRoles, CollaborationStage
from core.agent_factory import AgentBuild, AgentReviewReport, AgentTestReport, GeneratedFile
from core.agent_specs import AgentLifecycle, AgentSpec
from core.ai_factory_stage131_adapters import RoleEvidenceInput
from core.ai_factory_stage133_orchestration import (
    Stage133ModelConfigs,
    build_stage133_runtime,
)
from core.ai_factory_stage132_local_models import LocalModelConfig
from core.capability_gap_discovery import CapabilityGap, CapabilityRequirement


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def chat(self, *, system, prompt):
        self.calls.append((system, prompt))
        return self.content


class FakeBuilder:
    def build(self, spec):
        return AgentBuild(
            spec=spec,
            files=(
                GeneratedFile("agents/generated/repo-auditor.py", "class Auditor: pass"),
                GeneratedFile("tests/agents/generated/test_repo_auditor.py", "def test_ok(): assert True"),
            ),
        )


class FakeSandbox:
    def test(self, build):
        return AgentTestReport(True, ("sandbox pytest: 1 passed",), ())


class FakeReviewer:
    def review(self, build, tests):
        return AgentReviewReport(True, ("read-only scope checked",), ())


def make_gap():
    return CapabilityGap(
        gap_id="capability-gap-stage133",
        requirement=CapabilityRequirement(
            key="repository-auditing",
            description="Audit repository changes using evidence",
            validation_tests=("reject_unverified_claims",),
        ),
        evidence=("no enabled auditor is registered",),
    )


def json_spec():
    return (
        '{"name":"repo-auditor","purpose":"Audit diffs",'
        '"input_contract":"Diff and evidence","output_contract":"Findings",'
        '"tests":["reject_missing_evidence"]}'
    )


def make_runtime(*, test_passed=True, review_approved=True, model_design=None, model_arch=None, model_build=None):
    design_client = FakeClient(model_design or json_spec())
    architect_client = FakeClient(model_arch or "Design proposal")
    builder_client = FakeClient(model_build or "Build proposal")
    test_gate = lambda gap, stage: RoleEvidenceInput(
        agent="tester-ai", summary="Independent test result",
        content="CI sandbox evidence", observations=("run-id: 123",),
        passed=test_passed,
    )
    review_gate = lambda gap, stage: RoleEvidenceInput(
        agent="reviewer-ai", summary="Independent review",
        content="Review findings", observations=("review record: 456",),
        approved=review_approved,
    )
    runtime = build_stage133_runtime(
        configs=Stage133ModelConfigs(
            designer=LocalModelConfig("designer-model"),
            architect_role=LocalModelConfig("architect-model"),
            builder_role=LocalModelConfig("builder-model"),
        ),
        roles=CollaborationRoles("architect-ai", "builder-ai", "tester-ai", "reviewer-ai"),
        builder=FakeBuilder(),
        sandbox=FakeSandbox(),
        reviewer=FakeReviewer(),
        test_gate=test_gate,
        review_gate=review_gate,
    )
    # Replace the loopback clients only in this test fixture, without network I/O.
    runtime.factory.gap_architect.designer.client = design_client
    runtime.local_role_producer.clients_by_stage[CollaborationStage.DESIGN] = architect_client
    runtime.local_role_producer.clients_by_stage[CollaborationStage.BUILD] = builder_client
    return runtime, (design_client, architect_client, builder_client)


def test_stage133_wires_local_models_through_all_four_roles_to_candidate():
    runtime, clients = make_runtime()
    result = runtime.propose(make_gap())
    assert result.candidate is not None
    assert result.candidate.state.value == "awaiting_approval"
    assert [len(client.calls) for client in clients] == [1, 1, 1]
    assert runtime.factory.orchestrator.catalog.entries() == ()


def test_stage133_blocks_when_independent_test_fails_before_candidate_build():
    runtime, _ = make_runtime(test_passed=False)
    result = runtime.propose(make_gap())
    assert result.candidate is None
    assert "not complete" in result.blocked_reason.lower()
    assert runtime.factory.factory_adapter.factory.get_candidate("repo-auditor") is None


def test_stage133_blocks_when_independent_review_rejects():
    runtime, _ = make_runtime(review_approved=False)
    result = runtime.propose(make_gap())
    assert result.candidate is None
    assert "not complete" in result.blocked_reason.lower()
    assert runtime.factory.factory_adapter.factory.get_candidate("repo-auditor") is None


def test_stage133_requires_four_distinct_role_names():
    with pytest.raises(ValueError, match="distinct agent identities"):
        build_stage133_runtime(
            configs=Stage133ModelConfigs(
                LocalModelConfig("designer"),
                LocalModelConfig("architect"),
                LocalModelConfig("builder"),
            ),
            roles=CollaborationRoles("same", "same", "tester", "reviewer"),
            builder=FakeBuilder(), sandbox=FakeSandbox(), reviewer=FakeReviewer(),
            test_gate=lambda *_: None, review_gate=lambda *_: None,
        )


def test_stage133_rejects_missing_independent_gates():
    with pytest.raises(ValueError, match="independent"):
        build_stage133_runtime(
            configs=Stage133ModelConfigs(
                LocalModelConfig("designer"),
                LocalModelConfig("architect"),
                LocalModelConfig("builder"),
            ),
            roles=CollaborationRoles("a", "b", "c", "d"),
            builder=FakeBuilder(), sandbox=FakeSandbox(), reviewer=FakeReviewer(),
            test_gate=None, review_gate=lambda *_: None,
        )


def test_stage133_requires_distinct_test_and_review_gate_objects():
    shared_gate = lambda *_: None
    with pytest.raises(ValueError, match="separate independent"):
        build_stage133_runtime(
            configs=Stage133ModelConfigs(
                LocalModelConfig("designer"),
                LocalModelConfig("architect"),
                LocalModelConfig("builder"),
            ),
            roles=CollaborationRoles("a", "b", "c", "d"),
            builder=FakeBuilder(), sandbox=FakeSandbox(), reviewer=FakeReviewer(),
            test_gate=shared_gate, review_gate=shared_gate,
        )


def test_stage133_never_configures_human_approval_or_auto_activation():
    runtime, _ = make_runtime()
    factory = runtime.factory.factory_adapter.factory
    assert factory.approval_gate is None
    result = runtime.propose(make_gap())
    assert result.candidate is not None
    assert runtime.factory.orchestrator.catalog.find_enabled("repository-auditing") == ()
