import pytest

from core.agent_collaboration_pipeline import (
    AgentCollaborationPipeline,
    CollaborationRoles,
    CollaborationStage,
    HandoffEvidence,
)


def roles():
    return CollaborationRoles("architect-ai", "builder-ai", "tester-ai", "reviewer-ai")


def evidence(stage, agent, **overrides):
    values = {
        "evidence_id": f"{stage.value}-001",
        "stage": stage,
        "agent": agent,
        "summary": f"{stage.value} completed",
        "content": f"immutable {stage.value} artifact",
        "observations": ("artifact produced", "scope checked"),
    }
    values.update(overrides)
    return HandoffEvidence(**values)


def full_pipeline():
    pipeline = AgentCollaborationPipeline()
    packet = pipeline.create("collab-1", "build a bounded research agent", roles())
    packet = pipeline.advance(packet, evidence(CollaborationStage.DESIGN, "architect-ai"))
    packet = pipeline.advance(packet, evidence(CollaborationStage.BUILD, "builder-ai"))
    packet = pipeline.advance(
        packet, evidence(CollaborationStage.TEST, "tester-ai", passed=True)
    )
    packet = pipeline.advance(
        packet, evidence(CollaborationStage.REVIEW, "reviewer-ai", approved=True)
    )
    return pipeline, packet


def test_pipeline_requires_four_distinct_roles():
    with pytest.raises(ValueError, match="independent agents"):
        AgentCollaborationPipeline().create(
            "x", "task", CollaborationRoles("same", "same", "tester", "reviewer")
        )


def test_happy_path_requires_design_build_test_and_independent_review():
    _, packet = full_pipeline()
    assert packet.current_stage is CollaborationStage.COMPLETE
    assert [item.stage for item in packet.evidence] == [
        CollaborationStage.DESIGN,
        CollaborationStage.BUILD,
        CollaborationStage.TEST,
        CollaborationStage.REVIEW,
    ]
    assert len(packet.evidence_digests) == 4


def test_wrong_agent_cannot_advance_stage():
    pipeline = AgentCollaborationPipeline()
    packet = pipeline.create("c", "task", roles())
    with pytest.raises(PermissionError, match="assigned architect"):
        pipeline.advance(packet, evidence(CollaborationStage.DESIGN, "builder-ai"))


def test_wrong_stage_evidence_is_rejected():
    pipeline = AgentCollaborationPipeline()
    packet = pipeline.create("c", "task", roles())
    with pytest.raises(ValueError, match="does not match"):
        pipeline.advance(packet, evidence(CollaborationStage.BUILD, "builder-ai"))


def test_test_failure_blocks_review_and_all_later_stages():
    pipeline = AgentCollaborationPipeline()
    packet = pipeline.create("c", "task", roles())
    packet = pipeline.advance(packet, evidence(CollaborationStage.DESIGN, "architect-ai"))
    packet = pipeline.advance(packet, evidence(CollaborationStage.BUILD, "builder-ai"))
    packet = pipeline.advance(
        packet,
        evidence(CollaborationStage.TEST, "tester-ai", passed=False),
    )
    assert packet.current_stage is CollaborationStage.BLOCKED
    assert packet.blocked_reason
    with pytest.raises(ValueError, match="terminal"):
        pipeline.advance(packet, evidence(CollaborationStage.REVIEW, "reviewer-ai", approved=True))


def test_review_blocker_prevents_completion():
    pipeline = AgentCollaborationPipeline()
    packet = pipeline.create("c", "task", roles())
    packet = pipeline.advance(packet, evidence(CollaborationStage.DESIGN, "architect-ai"))
    packet = pipeline.advance(packet, evidence(CollaborationStage.BUILD, "builder-ai"))
    packet = pipeline.advance(packet, evidence(CollaborationStage.TEST, "tester-ai", passed=True))
    packet = pipeline.advance(
        packet,
        evidence(
            CollaborationStage.REVIEW,
            "reviewer-ai",
            approved=False,
            blockers=("permission boundary unclear",),
        ),
    )
    assert packet.current_stage is CollaborationStage.BLOCKED
    assert "review" in packet.blocked_reason


def test_review_cannot_claim_approved_with_blockers():
    item = evidence(
        CollaborationStage.REVIEW,
        "reviewer-ai",
        approved=True,
        blockers=("blocker",),
    )
    assert "approved review cannot contain blockers" in item.validate()


def test_duplicate_evidence_id_is_rejected():
    pipeline = AgentCollaborationPipeline()
    packet = pipeline.create("c", "task", roles())
    first = evidence(CollaborationStage.DESIGN, "architect-ai")
    packet = pipeline.advance(packet, first)
    duplicate = evidence(CollaborationStage.BUILD, "builder-ai", evidence_id=first.evidence_id)
    with pytest.raises(ValueError, match="duplicate evidence_id"):
        pipeline.advance(packet, duplicate)


def test_pipeline_preserves_human_approval_and_no_deploy_constraints():
    _, packet = full_pipeline()
    assert "human approval required for production activation" in packet.safety_constraints
    assert "no automatic merge" in packet.safety_constraints
    assert "no automatic deployment" in packet.safety_constraints


def test_evidence_digest_is_stable_and_content_bound():
    item = evidence(CollaborationStage.DESIGN, "architect-ai")
    assert item.content_sha256 == evidence(CollaborationStage.DESIGN, "architect-ai").content_sha256
    changed = evidence(CollaborationStage.DESIGN, "architect-ai", content="changed")
    assert item.content_sha256 != changed.content_sha256


def test_packet_is_immutable_across_transitions():
    pipeline = AgentCollaborationPipeline()
    original = pipeline.create("c", "task", roles())
    advanced = pipeline.advance(
        original, evidence(CollaborationStage.DESIGN, "architect-ai")
    )
    assert original.current_stage is CollaborationStage.DESIGN
    assert original.evidence == ()
    assert advanced.current_stage is CollaborationStage.BUILD
