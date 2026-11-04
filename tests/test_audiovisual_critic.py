from copy import deepcopy

from agents.media.audiovisual_critic import review_audiovisual_draft
from agents.music.score_plan import build_music_plan
from agents.video.edit_decision_list import build_edit_decision_list
from agents.video.scenario import build_scenario
from agents.video.storyboard import build_storyboard


def _bundle():
    scenario = build_scenario("夜明けの街で始まる小さな物語", duration_seconds=40, scene_count=4)
    music = build_music_plan(scenario)
    edl = build_edit_decision_list(scenario, music)
    storyboard = build_storyboard(scenario)
    return scenario, music, edl, storyboard


def test_creator_critic_reports_structural_review_and_does_not_authorize_publication():
    scenario, music, edl, storyboard = _bundle()
    report = review_audiovisual_draft(scenario, music, edl, storyboard)

    assert report["schema_version"] == "audiovisual-creator-critic.v1"
    assert report["status"] in {"HOLD", "REVIEW_REQUIRED", "STRUCTURAL_CHECKS_PASS"}
    assert 0 <= report["structural_score"] <= 100
    assert report["score_is_subjective_quality"] is False
    assert report["publication_authorized"] is False
    assert report["assets_modified"] is False
    assert any(item["code"] == "rights_review_required" for item in report["findings"])


def test_creator_critic_holds_when_visual_and_audio_sync_anchors_diverge():
    scenario, music, edl, storyboard = _bundle()
    edl = deepcopy(edl)
    edl["video_track"][0]["visual_sync_points"][0]["event"] = "different event"

    report = review_audiovisual_draft(scenario, music, edl, storyboard)

    assert report["status"] == "HOLD"
    assert report["blocker_count"] >= 1
    assert any(item["code"] == "sync_anchor_mismatch" for item in report["findings"])


def test_creator_critic_warns_when_music_energy_conflicts_with_scenario():
    scenario, music, edl, storyboard = _bundle()
    music = deepcopy(music)
    music["cues"][0]["energy"] = "high"

    report = review_audiovisual_draft(scenario, music, edl, storyboard)

    assert any(item["code"] == "emotional_energy_mismatch" for item in report["findings"])


def test_creator_critic_rejects_unknown_artifact_schemas():
    scenario, music, edl, storyboard = _bundle()
    scenario["schema_version"] = "unknown.v1"

    try:
        review_audiovisual_draft(scenario, music, edl, storyboard)
    except ValueError as exc:
        assert "scenario" in str(exc)
    else:
        raise AssertionError("unknown scenario schema must fail closed")

def test_creator_critic_is_deterministic_and_does_not_mutate_inputs():
    scenario, music, edl, storyboard = _bundle()
    before = deepcopy((scenario, music, edl, storyboard))

    first = review_audiovisual_draft(scenario, music, edl, storyboard)
    second = review_audiovisual_draft(scenario, music, edl, storyboard)

    assert first == second
    assert (scenario, music, edl, storyboard) == before
