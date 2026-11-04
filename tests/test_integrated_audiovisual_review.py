from copy import deepcopy

from agents.media.integrated_audiovisual_review import review_audiovisual_production
from agents.music.score_plan import build_music_plan
from agents.video.edit_decision_list import build_edit_decision_list
from agents.video.scenario import build_scenario
from agents.video.storyboard import build_storyboard


def _bundle():
    scenario = build_scenario("夜明けの街で始まる物語", duration_seconds=40, scene_count=4)
    music = build_music_plan(scenario)
    edl = build_edit_decision_list(scenario, music)
    storyboard = build_storyboard(scenario)
    signal = {
        "schema_version": "audiovisual-bundle-signal-report.v1",
        "video_coverage": {
            "scenario_duration_seconds": 40,
            "sampled_through_seconds": 40.0,
            "sampling_limit_reached": False,
            "scenario_coverage_complete": True,
            "uncovered_scene_ids": [],
            "partially_covered_scene_ids": [],
        },
        "scene_comparison": {
            "schema_version": "audiovisual-scene-signal-report.v1",
            "scenes": [
                {
                    "scene_id": scene["scene_id"],
                    "audio_window_count": 2,
                    "audio_mean_rms_dbfs": -24.0 + index * 2,
                    "audio_mean_spectral_centroid_hz": 900.0 + index * 100,
                    "video_sample_count": 2,
                    "video_mean_luma": 70.0 + index * 10,
                    "video_mean_frame_change_luma": 2.0 + index,
                }
                for index, scene in enumerate(scenario["scenes"])
            ],
        },
        "publication_authorized": False,
        "assets_modified": False,
    }
    return scenario, music, edl, storyboard, signal


def test_integrated_review_aligns_intent_and_measured_signals_without_authorizing_publication():
    scenario, music, edl, storyboard, signal = _bundle()
    before = deepcopy((scenario, music, edl, storyboard, signal))

    report = review_audiovisual_production(scenario, music, edl, storyboard, signal)

    assert report["schema_version"] == "integrated-audiovisual-review.v1"
    assert len(report["signal_alignment"]["scenes"]) == 4
    assert report["signal_alignment"]["scenes"][0]["measured_audio_rms_dbfs"] == -24.0
    assert report["signal_alignment"]["automatic_quality_judgment"] is False
    assert report["publication_authorized"] is False
    assert report["assets_modified"] is False
    assert (scenario, music, edl, storyboard, signal) == before


def test_integrated_review_warns_when_video_coverage_is_incomplete():
    scenario, music, edl, storyboard, signal = _bundle()
    signal["video_coverage"]["scenario_coverage_complete"] = False
    signal["video_coverage"]["uncovered_scene_ids"] = [scenario["scenes"][-1]["scene_id"]]

    report = review_audiovisual_production(scenario, music, edl, storyboard, signal)

    # Existing structural blockers must remain HOLD; the coverage warning
    # supplements findings and must never downgrade a stronger safety status.
    assert report["status"] in {"HOLD", "REVIEW_REQUIRED"}
    assert any(item["code"] == "measured_video_coverage_incomplete" for item in report["findings"])


def test_integrated_review_rejects_missing_coverage_contract():
    scenario, music, edl, storyboard, signal = _bundle()
    del signal["video_coverage"]

    try:
        review_audiovisual_production(scenario, music, edl, storyboard, signal)
    except ValueError as exc:
        assert "video coverage" in str(exc)
    else:
        raise AssertionError("missing coverage must fail closed")
