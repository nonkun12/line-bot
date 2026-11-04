import copy

import pytest

from agents.media.creator_revision_briefs import build_creator_revision_briefs


def _feedback():
    return {
        "schema_version": "audiovisual-creator-feedback.v1",
        "proposal_count": 1,
        "proposals": [{
            "proposal_id": "FB-001",
            "source_finding_code": "dialogue_mix_conflict",
            "scene_id": "SC02",
            "domain": "music",
            "suggestion": "台詞の明瞭さを優先した編成案を作る。",
            "evidence": {"finding_message": "SC02: dialogue mix conflict"},
            "requires_human_review": True,
            "requires_human_approval_before_application": True,
        }],
        "execution_policy": {
            "mode": "proposal_only",
            "automatic_asset_changes": False,
            "automatic_publication": False,
            "publication_authorized": False,
            "blockers_present": True,
            "blockers_must_be_resolved_before_production": True,
        },
    }


def test_builds_two_bounded_alternatives_without_mutating_feedback():
    feedback = _feedback()
    before = copy.deepcopy(feedback)

    result = build_creator_revision_briefs(feedback)

    assert feedback == before
    assert result["schema_version"] == "audiovisual-creator-revision-briefs.v1"
    assert result["brief_count"] == 2
    assert [item["variant"] for item in result["briefs"]] == ["conservative", "exploratory"]
    assert all(item["source_proposal_id"] == "FB-001" for item in result["briefs"])
    assert all(item["scene_id"] == "SC02" for item in result["briefs"])
    assert all(item["apply_revision"] is False for item in result["briefs"])
    assert all(item["requires_human_approval_before_application"] for item in result["briefs"])
    assert result["execution_policy"]["production_blocked"] is True
    assert result["execution_policy"]["automatic_revision_application"] is False
    assert result["execution_policy"]["automatic_asset_changes"] is False
    assert result["execution_policy"]["automatic_publication"] is False
    assert result["execution_policy"]["publication_authorized"] is False


def test_empty_proposals_produce_empty_briefs():
    feedback = _feedback()
    feedback["proposals"] = []

    result = build_creator_revision_briefs(feedback)

    assert result["brief_count"] == 0
    assert result["briefs"] == []


def test_rejects_feedback_without_explicit_safe_policy():
    feedback = _feedback()
    feedback["execution_policy"]["automatic_publication"] = True

    with pytest.raises(ValueError, match="prohibit automatic publication"):
        build_creator_revision_briefs(feedback)


def test_rejects_proposal_that_does_not_require_human_approval():
    feedback = _feedback()
    feedback["proposals"][0]["requires_human_approval_before_application"] = False

    with pytest.raises(ValueError, match="require human approval"):
        build_creator_revision_briefs(feedback)
