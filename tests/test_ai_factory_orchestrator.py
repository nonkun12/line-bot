from types import SimpleNamespace

import pytest

from core.agent_collaboration_pipeline import (
    AgentCollaborationPipeline,
    CollaborationRoles,
    CollaborationStage,
    HandoffEvidence,
)
from core.ai_factory_orchestrator import (
    AIFactoryOrchestrator,
    ApprovalReceipt,
    CandidateState,
    CapabilityGapRequest,
    LoopSafety,
    SpecialistAgentCatalog,
)


def gap(gap_id="gap-1"):
    return CapabilityGapRequest(
        gap_id=gap_id,
        capability="repository-auditing",
        description="Inspect repository changes and report evidence",
        evidence=("no enabled specialist is registered",),
    )


def completed_packet(gap_request):
    pipeline = AgentCollaborationPipeline()
    packet = pipeline.create(
        f"collab-{gap_request.gap_id}",
        gap_request.description,
        CollaborationRoles("architect", "builder", "tester", "reviewer"),
    )
    stages = (
        (CollaborationStage.DESIGN, "architect", {}),
        (CollaborationStage.BUILD, "builder", {}),
        (CollaborationStage.TEST, "tester", {"passed": True}),
        (CollaborationStage.REVIEW, "reviewer", {"approved": True}),
    )
    for stage, agent, extra in stages:
        packet = pipeline.advance(
            packet,
            HandoffEvidence(
                evidence_id=f"{gap_request.gap_id}-{stage.value}",
                stage=stage,
                agent=agent,
                summary=f"{stage.value} complete",
                content=f"{stage.value} artifact",
                observations=("evidence captured",),
                **extra,
            ),
        )
    return packet


class Collaboration:
    def collaborate(self, gap_request):
        return completed_packet(gap_request)


class Factory:
    def create_candidate(self, capability_gap):
        spec = SimpleNamespace(name="repository-auditor")
        files = (
            SimpleNamespace(path="agents/generated/auditor.py", content="class Auditor: pass"),
            SimpleNamespace(path="tests/agents/generated/test_auditor.py", content="def test_ok(): assert True"),
        )
        return SimpleNamespace(
            build=SimpleNamespace(spec=spec, files=files),
            tests=SimpleNamespace(passed=True, evidence=("pytest: 4 passed",), failures=()),
            review=SimpleNamespace(approved=True, findings=("least privilege checked",), blockers=()),
        )


class Verifier:
    def verify(self, candidate, receipt):
        return (
            receipt.candidate_id == candidate.candidate_id
            and receipt.scope in {"register", "enable"}
            and receipt.approved_by == "human-operator"
            and receipt.approval_id.startswith("approval-")
        )


class Activator:
    def __init__(self, result=True):
        self.result = result
        self.calls = 0

    def activate(self, candidate):
        self.calls += 1
        return self.result


def orchestrator():
    return AIFactoryOrchestrator(Collaboration(), Factory())


def test_stage_126_to_129_builds_candidate_but_does_not_self_register_or_enable():
    result = orchestrator().process_gap(gap())
    assert result.candidate is not None
    assert result.candidate.state is CandidateState.AWAITING_APPROVAL
    assert result.candidate.agent_name == "repository-auditor"
    assert len(result.candidate.artifact_sha256) == 64


def test_catalog_rejects_registration_without_human_receipt():
    candidate = orchestrator().process_gap(gap()).candidate
    catalog = SpecialistAgentCatalog()
    with pytest.raises(PermissionError, match="receipt"):
        catalog.register_approved(
            candidate,
            ApprovalReceipt(candidate.candidate_id, "enable", "human-operator", "approval-1"),
            Verifier(),
        )
    assert catalog.entries() == ()


def test_catalog_registration_requires_verified_register_scope_and_stays_disabled():
    candidate = orchestrator().process_gap(gap()).candidate
    catalog = SpecialistAgentCatalog()
    receipt = ApprovalReceipt(candidate.candidate_id, "register", "human-operator", "approval-1")
    entry = catalog.register_approved(candidate, receipt, Verifier())
    assert entry.state is CandidateState.APPROVED
    assert catalog.find_enabled("repository-auditing") == ()


def test_activation_requires_separate_human_approval():
    candidate = orchestrator().process_gap(gap()).candidate
    catalog = SpecialistAgentCatalog()
    catalog.register_approved(
        candidate,
        ApprovalReceipt(candidate.candidate_id, "register", "human-operator", "approval-1"),
        Verifier(),
    )
    activator = Activator()
    with pytest.raises(PermissionError, match="separate human"):
        catalog.mark_enabled(
            candidate.candidate_id,
            ApprovalReceipt(candidate.candidate_id, "register", "human-operator", "approval-2"),
            Verifier(),
            activator,
        )
    assert activator.calls == 0


def test_explicit_enable_receipt_and_activator_are_both_required():
    candidate = orchestrator().process_gap(gap()).candidate
    catalog = SpecialistAgentCatalog()
    catalog.register_approved(
        candidate,
        ApprovalReceipt(candidate.candidate_id, "register", "human-operator", "approval-1"),
        Verifier(),
    )
    entry = catalog.mark_enabled(
        candidate.candidate_id,
        ApprovalReceipt(candidate.candidate_id, "enable", "human-operator", "approval-2"),
        Verifier(),
        Activator(),
    )
    assert entry.state is CandidateState.ENABLED
    assert len(catalog.find_enabled("repository-auditing")) == 1


def test_activation_failure_does_not_mark_catalog_entry_enabled():
    candidate = orchestrator().process_gap(gap()).candidate
    catalog = SpecialistAgentCatalog()
    catalog.register_approved(
        candidate,
        ApprovalReceipt(candidate.candidate_id, "register", "human-operator", "approval-1"),
        Verifier(),
    )
    with pytest.raises(RuntimeError, match="did not confirm"):
        catalog.mark_enabled(
            candidate.candidate_id,
            ApprovalReceipt(candidate.candidate_id, "enable", "human-operator", "approval-2"),
            Verifier(),
            Activator(False),
        )
    assert catalog.get(candidate.candidate_id).state is CandidateState.APPROVED


@pytest.mark.parametrize(
    ("safety", "reason"),
    [
        (LoopSafety(kill_switch_active=True), "kill switch"),
        (LoopSafety(hold_active=True), "HOLD"),
        (LoopSafety(evidence_complete=False), "evidence"),
        (LoopSafety(budget_available=False), "budget"),
    ],
)
def test_stage_130_loop_fails_closed(safety, reason):
    report = orchestrator().run_tick("tick-1", (gap(),), safety=safety)
    assert report.processed == ()
    assert reason.lower() in report.stopped_reason.lower()


def test_stage_130_tick_is_bounded_to_four_candidates():
    gaps = tuple(gap(f"gap-{index}") for index in range(7))
    report = orchestrator().run_tick("tick-2", gaps)
    assert report.created_candidates == 4
    assert len(report.processed) == 4


def test_stage_130_rejects_unbounded_tick_configuration():
    report = orchestrator().run_tick("tick-3", (gap(),), safety=LoopSafety(max_candidates_per_tick=5))
    assert report.processed == ()
    assert "between 1 and 4" in report.stopped_reason


def test_incomplete_collaboration_blocks_candidate_creation():
    class IncompleteCollaboration:
        def collaborate(self, gap_request):
            pipeline = AgentCollaborationPipeline()
            return pipeline.create(
                "unfinished",
                gap_request.description,
                CollaborationRoles("architect", "builder", "tester", "reviewer"),
            )

    result = AIFactoryOrchestrator(IncompleteCollaboration(), Factory()).process_gap(gap())
    assert result.candidate is None
    assert "not complete" in result.blocked_reason


def test_invalid_gap_is_blocked_without_calling_factory():
    class NeverFactory:
        def create_candidate(self, capability_gap):
            raise AssertionError("factory must not be called")

    invalid = CapabilityGapRequest("", "", "", ())
    result = AIFactoryOrchestrator(Collaboration(), NeverFactory()).process_gap(invalid)
    assert result.candidate is None
    assert "gap_id is required" in result.blocked_reason


def test_duplicate_gap_ids_are_blocked_within_one_tick():
    request = gap()
    report = orchestrator().run_tick("tick-4", (request, request))
    assert len(report.processed) == 2
    assert report.processed[0].candidate is not None
    assert report.processed[1].blocked_reason == "duplicate gap id"
