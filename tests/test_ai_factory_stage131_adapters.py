from types import SimpleNamespace

import pytest

from core.agent_collaboration_pipeline import CollaborationRoles, CollaborationStage
from core.ai_factory_orchestrator import (
    AIFactoryOrchestrator,
    CandidateState,
    SpecialistAgentCatalog,
)
from core.ai_factory_stage131_adapters import (
    RoleEvidenceInput,
    Stage121FactoryAdapter,
    Stage123EvidenceRunner,
    Stage131AIFactory,
)
from core.capability_gap_discovery import (
    CapabilityGap,
    CapabilityGapArchitect,
    CapabilityRequirement,
)


class Designer:
    def design(self, gap):
        return object()


class FakeStage121Factory:
    def __init__(self, architect):
        self.architect = architect
        self.calls = []

    def create_candidate(self, capability_gap):
        self.calls.append(capability_gap)
        return SimpleNamespace(
            build=SimpleNamespace(
                spec=SimpleNamespace(name="specialist-auditor"),
                files=(
                    SimpleNamespace(path="agents/generated/auditor.py", content="class Auditor: pass"),
                    SimpleNamespace(path="tests/agents/generated/test_auditor.py", content="def test_ok(): assert True"),
                ),
            ),
            tests=SimpleNamespace(passed=True, evidence=("isolated pytest: 3 passed",), failures=()),
            review=SimpleNamespace(approved=True, findings=("least privilege reviewed",), blockers=()),
        )


def build_gap():
    requirement = CapabilityRequirement(
        key="repository-auditing",
        description="Audit repository changes with evidence",
        validation_tests=("test_read_only",),
    )
    return CapabilityGap(
        gap_id="capability-gap-a1b2c3d4",
        requirement=requirement,
        evidence=("no enabled repository auditor exists",),
    )


def role_producer(expected_agent, *, passed=None, approved=None):
    def produce(gap, stage):
        return RoleEvidenceInput(
            agent=expected_agent,
            summary=f"{stage.value} evidence",
            content=f"{stage.value} output for {gap.gap_id}",
            observations=("source checked",),
            passed=passed,
            approved=approved,
        )
    return produce


def build_system():
    roles = CollaborationRoles("architect-ai", "builder-ai", "tester-ai", "reviewer-ai")
    producers = {
        CollaborationStage.DESIGN: role_producer(roles.architect),
        CollaborationStage.BUILD: role_producer(roles.builder),
        CollaborationStage.TEST: role_producer(roles.tester, passed=True),
        CollaborationStage.REVIEW: role_producer(roles.reviewer, approved=True),
    }
    collaboration = Stage123EvidenceRunner(roles=roles, producers=producers)
    gap_architect = CapabilityGapArchitect(Designer())
    stage121 = FakeStage121Factory(gap_architect)
    factory_adapter = Stage121FactoryAdapter(factory=stage121, gap_architect=gap_architect)
    orchestrator = AIFactoryOrchestrator(collaboration, factory_adapter)
    integrated = Stage131AIFactory(
        gap_architect=gap_architect,
        factory_adapter=factory_adapter,
        collaboration=collaboration,
        orchestrator=orchestrator,
    )
    return integrated, stage121, orchestrator


def test_stage131_connects_gap_to_stage123_and_stage121_candidate_factory():
    integrated, stage121, orchestrator = build_system()
    result = integrated.propose(build_gap())
    assert result.candidate is not None
    assert result.candidate.state is CandidateState.AWAITING_APPROVAL
    assert stage121.calls == ["capability-gap-a1b2c3d4"]
    assert orchestrator.catalog.entries() == ()


def test_stage131_does_not_create_candidate_when_test_evidence_fails():
    integrated, stage121, _ = build_system()
    roles = integrated.collaboration.roles
    integrated.collaboration.producers[CollaborationStage.TEST] = role_producer(
        roles.tester, passed=False
    )
    result = integrated.propose(build_gap())
    assert result.candidate is None
    assert "blocked" in result.blocked_reason.lower() or "not complete" in result.blocked_reason.lower()
    assert stage121.calls == []


def test_stage131_does_not_create_candidate_when_review_is_rejected():
    integrated, stage121, _ = build_system()
    roles = integrated.collaboration.roles
    integrated.collaboration.producers[CollaborationStage.REVIEW] = role_producer(
        roles.reviewer, approved=False
    )
    result = integrated.propose(build_gap())
    assert result.candidate is None
    assert stage121.calls == []


def test_stage131_rejects_inconsistent_adapter_wiring():
    integrated, _, orchestrator = build_system()
    wrong = AIFactoryOrchestrator(integrated.collaboration, object())
    with pytest.raises(ValueError, match="factory adapter"):
        Stage131AIFactory(
            gap_architect=integrated.gap_architect,
            factory_adapter=integrated.factory_adapter,
            collaboration=integrated.collaboration,
            orchestrator=wrong,
        )


def test_stage131_never_auto_registers_or_enables_candidate():
    integrated, _, _ = build_system()
    result = integrated.propose(build_gap())
    assert result.candidate is not None
    assert integrated.orchestrator.catalog.find_enabled("repository-auditing") == ()
    assert integrated.orchestrator.catalog.entries() == ()


def test_stage123_runner_requires_all_four_independent_producers():
    roles = CollaborationRoles("a", "b", "c", "d")
    with pytest.raises(ValueError, match="exactly four"):
        Stage123EvidenceRunner(
            roles=roles,
            producers={CollaborationStage.DESIGN: role_producer("a")},
        )


def test_stage123_runner_rejects_role_spoofing():
    roles = CollaborationRoles("a", "b", "c", "d")
    producers = {
        CollaborationStage.DESIGN: role_producer("not-a"),
        CollaborationStage.BUILD: role_producer("b"),
        CollaborationStage.TEST: role_producer("c", passed=True),
        CollaborationStage.REVIEW: role_producer("d", approved=True),
    }
    runner = Stage123EvidenceRunner(roles=roles, producers=producers)
    with pytest.raises(PermissionError, match="architect"):
        runner.collaborate(
            SimpleNamespace(
                gap_id="g-1",
                capability="audit",
                description="audit",
                evidence=("gap",),
            )
        )
