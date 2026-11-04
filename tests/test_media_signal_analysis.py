import struct
import wave

import pytest

from agents.media.signal_analysis import (
    analyze_video_signal,
    analyze_wav_signal,
    compare_scene_signals,
)


def _wav(path):
    rate = 8000
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        samples = []
        for index in range(rate * 2):
            value = int(9000 * (1 if index % 80 < 40 else -1))
            samples.append(struct.pack("<h", value))
        writer.writeframes(b"".join(samples))


def test_wav_analysis_reports_bounded_per_window_signal_features(tmp_path):
    path = tmp_path / "test.wav"
    _wav(path)

    report = analyze_wav_signal(path, window_seconds=0.5)

    assert report["schema_version"] == "audiovisual-signal-analysis.v1"
    assert report["media_type"] == "audio"
    assert report["duration_seconds"] == 2.0
    assert len(report["windows"]) == 4
    assert all(-140 <= item["rms_dbfs"] <= 0 for item in report["windows"])
    assert all(0 <= item["zero_crossing_rate"] <= 1 for item in report["windows"])


def test_wav_analysis_rejects_duration_and_format_outside_bounds(tmp_path):
    path = tmp_path / "too-long.wav"
    rate = 8000
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\0\0" * (rate * 91))
    with pytest.raises(ValueError, match="duration"):
        analyze_wav_signal(path)


def test_video_analysis_uses_fixed_bounded_ffmpeg_command(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"placeholder")
    frame_size = 64 * 36 * 3
    dark = bytes([20, 20, 20]) * (64 * 36)
    bright = bytes([200, 100, 50]) * (64 * 36)

    class Result:
        returncode = 0
        stdout = dark + bright
        stderr = b""

    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr("agents.media.signal_analysis.subprocess.run", fake_run)
    report = analyze_video_signal(video, ffmpeg_executable="/usr/bin/ffmpeg")

    assert report["media_type"] == "video"
    assert len(report["samples"]) == 2
    assert report["samples"][0]["mean_luma"] < report["samples"][1]["mean_luma"]
    assert report["sampled_through_seconds"] == 2.0
    assert report["sampling_limit_reached"] is False
    args, kwargs = calls[0]
    assert "-frames:v" in args and "90" in args
    assert kwargs["timeout"] == 60
    assert kwargs["stdin"] is not None


def test_scene_signal_comparison_aggregates_audio_and_video_by_scene():
    audio = {
        "schema_version": "audiovisual-signal-analysis.v1",
        "media_type": "audio",
        "windows": [
            {"start_seconds": 0.0, "end_seconds": 0.5, "rms_dbfs": -20.0, "spectral_centroid_hz": 500.0},
            {"start_seconds": 0.5, "end_seconds": 1.0, "rms_dbfs": -10.0, "spectral_centroid_hz": 900.0},
        ],
    }
    video = {
        "schema_version": "audiovisual-signal-analysis.v1",
        "media_type": "video",
        "samples": [
            {"at_seconds": 0, "mean_luma": 40.0, "mean_saturation": 10.0, "frame_change_luma": 0.0},
            {"at_seconds": 1, "mean_luma": 120.0, "mean_saturation": 50.0, "frame_change_luma": 80.0},
        ],
    }

    report = compare_scene_signals(audio, video, [
        {"scene_id": "A", "time_start_seconds": 0, "duration_seconds": 1},
        {"scene_id": "B", "time_start_seconds": 1, "duration_seconds": 1},
    ])

    assert report["scene_count"] == 2
    assert report["scenes"][0]["audio_mean_rms_dbfs"] == -15.0
    assert report["scenes"][1]["video_mean_luma"] == 120.0


def test_scene_signal_comparison_rejects_invalid_scene_interval():
    audio = {"schema_version": "audiovisual-signal-analysis.v1", "media_type": "audio", "windows": []}
    video = {"schema_version": "audiovisual-signal-analysis.v1", "media_type": "video", "samples": []}
    with pytest.raises(ValueError, match="scene intervals"):
        compare_scene_signals(audio, video, [{"scene_id": "bad", "time_start_seconds": -1, "duration_seconds": 0}])


def test_bundle_analysis_connects_audio_video_and_scenario_by_scene(tmp_path, monkeypatch):
    from agents.media import signal_analysis

    audio_path = tmp_path / "draft.wav"
    video_path = tmp_path / "draft.mp4"
    audio_path.write_bytes(b"wav")
    video_path.write_bytes(b"mp4")
    scenario = {
        "schema_version": "video-scenario.v1",
        "title": "sample",
        "creative_brief": {"duration_seconds": 2},
        "scenes": [
            {"scene_id": "A", "time_start_seconds": 0, "duration_seconds": 1},
            {"scene_id": "B", "time_start_seconds": 1, "duration_seconds": 1},
        ],
    }
    monkeypatch.setattr(signal_analysis, "analyze_wav_signal", lambda path: {
        "schema_version": "audiovisual-signal-analysis.v1",
        "media_type": "audio",
        "duration_seconds": 2.0,
        "windows": [
            {"start_seconds": 0.0, "end_seconds": 1.0, "rms_dbfs": -20.0, "spectral_centroid_hz": 300.0},
            {"start_seconds": 1.0, "end_seconds": 2.0, "rms_dbfs": -12.0, "spectral_centroid_hz": 700.0},
        ],
    })
    monkeypatch.setattr(signal_analysis, "analyze_video_signal", lambda path, ffmpeg_executable=None: {
        "schema_version": "audiovisual-signal-analysis.v1",
        "media_type": "video",
        "samples": [
            {"at_seconds": 0, "mean_luma": 40.0, "mean_saturation": 20.0, "frame_change_luma": 0.0},
            {"at_seconds": 1, "mean_luma": 150.0, "mean_saturation": 60.0, "frame_change_luma": 110.0},
        ],
    })

    report = signal_analysis.analyze_audiovisual_bundle(scenario, audio_path, video_path)

    assert report["schema_version"] == "audiovisual-bundle-signal-report.v1"
    assert report["scene_comparison"]["scenes"][1]["audio_mean_rms_dbfs"] == -12.0
    assert report["scene_comparison"]["scenes"][1]["video_mean_luma"] == 150.0
    assert report["video_coverage"]["scenario_coverage_complete"] is True
    assert report["video_coverage"]["sampled_through_seconds"] == 2.0
    assert report["publication_authorized"] is False
    assert report["assets_modified"] is False


def test_signal_evidence_enriches_critic_report_without_mutation():
    from agents.media.signal_analysis import attach_signal_evidence_to_critic

    critic = {
        "schema_version": "audiovisual-creator-critic.v1",
        "status": "REVIEW_REQUIRED",
        "review_limits": ["Human review remains required."],
    }
    signal = {
        "schema_version": "audiovisual-bundle-signal-report.v1",
        "scene_comparison": {"scenes": [{"scene_id": "SC01", "audio_mean_rms_dbfs": -18.0, "video_mean_luma": 82.0}]},
    }
    original_critic = dict(critic)
    original_signal = {"scene_comparison": {"scenes": list(signal["scene_comparison"]["scenes"])}}

    enriched = attach_signal_evidence_to_critic(critic, signal)

    assert enriched["signal_evidence"]["scenes"][0]["scene_id"] == "SC01"
    assert enriched["signal_evidence"]["is_artistic_quality_score"] is False
    assert critic == original_critic
    assert signal["scene_comparison"] == original_signal["scene_comparison"]
    assert enriched["publication_authorized"] is False


def test_bundle_analysis_marks_scenes_beyond_video_sample_limit_uncovered(tmp_path, monkeypatch):
    from agents.media import signal_analysis

    audio_path = tmp_path / "draft.wav"
    video_path = tmp_path / "draft.mp4"
    audio_path.write_bytes(b"wav")
    video_path.write_bytes(b"mp4")
    scenario = {
        "schema_version": "video-scenario.v1",
        "title": "long sample",
        "creative_brief": {"duration_seconds": 100},
        "scenes": [
            {"scene_id": "EARLY", "time_start_seconds": 0, "duration_seconds": 90},
            {"scene_id": "LATE", "time_start_seconds": 90, "duration_seconds": 10},
        ],
    }
    monkeypatch.setattr(signal_analysis, "analyze_wav_signal", lambda path: {
        "schema_version": "audiovisual-signal-analysis.v1",
        "media_type": "audio",
        "duration_seconds": 100.0,
        "windows": [
            {"start_seconds": 0.0, "end_seconds": 100.0, "rms_dbfs": -20.0, "spectral_centroid_hz": 300.0},
        ],
    })
    monkeypatch.setattr(signal_analysis, "analyze_video_signal", lambda path, ffmpeg_executable=None: {
        "schema_version": "audiovisual-signal-analysis.v1",
        "media_type": "video",
        "sampled_through_seconds": 90.0,
        "sampling_limit_reached": True,
        "samples": [
            {"at_seconds": index, "mean_luma": 40.0, "mean_saturation": 20.0, "frame_change_luma": 0.0}
            for index in range(90)
        ],
    })

    report = signal_analysis.analyze_audiovisual_bundle(scenario, audio_path, video_path)

    assert report["video_coverage"]["scenario_coverage_complete"] is False
    assert report["video_coverage"]["sampling_limit_reached"] is True
    assert report["video_coverage"]["uncovered_scene_ids"] == ["LATE"]
    assert any("coverage is incomplete" in item for item in report["review_guidance"])
