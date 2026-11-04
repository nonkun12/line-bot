import pytest

from agents.media.revision_candidate_critic import review_creator_revision_candidates


def _briefs():
    return {
        "schema_version": "audiovisual-creator-revision-briefs.v1",
        "briefs": [{
            "brief_id": "FB-001-CONSERVATIVE",
            "source_proposal_id": "FB-001",
            "variant": "conservative",
            "preserve": ["story intent", "sync anchors"],
            "deliverables": ["change summary", "unchanged elements", "alternative", "risks and unknowns"],
        }],
        "execution_policy": {
            "automatic_revision_application": False,
            "automatic_asset_changes": False,
            "automatic_publication": False,
            "publication_authorized": False,
        },
    }


def _candidate():
    return {
        "candidate_id": "CAND-001",
        "brief_id": "FB-001-CONSERVATIVE",
        "change_summary": "Reduce accompaniment density under dialogue.",
        "preserved_elements": ["story intent", "sync anchors"],
        "deliverables": ["change summary", "unchanged elements", "alternative", "risks and unknowns"],
        "side_effects": ["The transition may feel less energetic."],
        "unknowns": ["Needs listening review on headphones and speakers."],
        "asset_changes_requested": False,
        "publication_requested": False,
    }


def test_complete_candidate_passes_structural_review_only():
    result = review_creator_revision_candidates(_briefs(), [_candidate()])

    assert result["status"] == "STRUCTURAL_CHECKS_PASS"
    assert result["reviewed_candidate_count"] == 1
    assert result["artistic_quality_assessed"] is False
    assert result["candidates"][0]["human_listening_and_viewing_required"] is True
    assert result["candidates"][0]["human_approval_required_before_application"] is True
    assert result["execution_policy"]["automatic_revision_application"] is False
    assert result["execution_policy"]["automatic_asset_changes"] is False
    assert result["execution_policy"]["automatic_publication"] is False
    assert result["execution_policy"]["publication_authorized"] is False


def test_missing_deliverable_or_preservation_is_review_required():
    candidate = _candidate()
    candidate["preserved_elements"] = ["story intent"]
    candidate["deliverables"] = ["change summary"]

    result = review_creator_revision_candidates(_briefs(), [candidate])

    assert result["status"] == "REVIEW_REQUIRED"
    codes = {item["code"] for item in result["findings"]}
    assert "preservation_not_confirmed" in codes
    assert "required_deliverables_missing" in codes


def test_unsafe_asset_or_publication_request_is_hold():
    candidate = _candidate()
    candidate["publication_requested"] = True

    result = review_creator_revision_candidates(_briefs(), [candidate])

    assert result["status"] == "HOLD"
    assert any(item["code"] == "unsafe_execution_request" for item in result["findings"])
    assert result["execution_policy"]["publication_authorized"] is False


def test_unknown_brief_reference_is_hold():
    candidate = _candidate()
    candidate["brief_id"] = "UNKNOWN"

    result = review_creator_revision_candidates(_briefs(), [candidate])

    assert result["status"] == "HOLD"
    assert any(item["code"] == "unknown_brief_reference" for item in result["findings"])


def test_missing_candidate_is_review_required():
    result = review_creator_revision_candidates(_briefs(), [])

    assert result["status"] == "REVIEW_REQUIRED"
    assert any(item["code"] == "briefs_without_candidates" for item in result["findings"])


def test_invalid_policy_is_rejected():
    briefs = _briefs()
    briefs["execution_policy"]["automatic_publication"] = True

    with pytest.raises(ValueError, match="prohibit automatic publication"):
        review_creator_revision_candidates(briefs, [])


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValueError):
        review_creator_revision_candidates({}, [])
    with pytest.raises(ValueError):
        review_creator_revision_candidates(_briefs(), {})
