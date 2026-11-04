import copy

import pytest

from agents.media.creator_feedback import build_creator_feedback_candidates


def _review():
    return {
        "schema_version": "integrated-audiovisual-review.v1",
        "status": "REVIEW_REQUIRED",
        "findings": [
            {
                "severity": "warning",
                "code": "dialogue_mix_conflict",
                "message": "SC02: dialogue mix needs review",
            },
            {
                "severity": "warning",
                "code": "storyboard_visual_drift",
                "message": "SC01: storyboard visual description differs",
            },
            {
                "severity": "blocker",
                "code": "sync_anchor_mismatch",
                "message": "SC03: sync anchors differ",
            },
            {
                "severity": "warning",
                "code": "unknown_future_finding",
                "message": "Do not infer a suggestion for unknown findings",
            },
        ],
        "signal_alignment": {
            "scenes": [
                {
                    "scene_id": "SC01",
                    "intended_energy": "low",
                    "measured_audio_rms_dbfs": -24.0,
                    "measured_audio_spectral_centroid_hz": 1200.0,
                    "measured_video_luma": 80.0,
                    "measured_video_frame_change_luma": 2.0,
                    "audio_samples_available": True,
                    "video_samples_available": True,
                },
                {
                    "scene_id": "SC02",
                    "intended_energy": "medium",
                    "measured_audio_rms_dbfs": -18.0,
                    "measured_audio_spectral_centroid_hz": 1800.0,
                    "measured_video_luma": 110.0,
                    "measured_video_frame_change_luma": 4.0,
                    "audio_samples_available": True,
                    "video_samples_available": True,
                },
            ]
        },
        "publication_authorized": False,
        "assets_modified": False,
    }


def test_feedback_candidates_are_evidence_linked_and_fail_closed():
    report = _review()
    before = copy.deepcopy(report)

    result = build_creator_feedback_candidates(report)

    assert report == before
    assert result["schema_version"] == "audiovisual-creator-feedback.v1"
    assert result["proposal_count"] == 2
    assert {item["source_finding_code"] for item in result["proposals"]} == {
        "dialogue_mix_conflict",
        "storyboard_visual_drift",
    }
    assert {item["scene_id"] for item in result["proposals"]} == {"SC01", "SC02"}
    assert all(item["requires_creator_review"] for item in result["proposals"])
    assert all(item["requires_human_approval_before_application"] for item in result["proposals"])
    assert result["execution_policy"]["blockers_present"] is True
    assert result["execution_policy"]["blockers_must_be_resolved_before_production"] is True
    assert result["execution_policy"]["automatic_source_edits"] is False
    assert result["execution_policy"]["automatic_asset_changes"] is False
    assert result["execution_policy"]["automatic_publication"] is False
    assert result["execution_policy"]["publication_authorized"] is False


def test_measurements_create_review_prompts_not_automatic_quality_findings():
    result = build_creator_feedback_candidates(_review())

    assert len(result["scene_review_prompts"]) == 2
    assert all(item["measurements_are_descriptive_only"] for item in result["scene_review_prompts"])
    assert "measured_audio_rms_dbfs" in result["scene_review_prompts"][0]["measurements"]


def test_unknown_findings_are_not_guessed_into_actions():
    report = _review()
    report["findings"] = [{"severity": "warning", "code": "unrecognized", "message": "SC01"}]

    result = build_creator_feedback_candidates(report)

    assert result["proposals"] == []
    assert result["proposal_count"] == 0


@pytest.mark.parametrize("bad", [None, {}, {"schema_version": "wrong"}])
def test_invalid_review_report_is_rejected(bad):
    with pytest.raises(ValueError):
        build_creator_feedback_candidates(bad)
