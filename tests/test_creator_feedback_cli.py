import json

from scripts import review_audiovisual_production as cli


def _inputs(tmp_path):
    values = {
        "--scenario": {"schema_version": "video-scenario.v1"},
        "--music-plan": {"schema_version": "video-music-plan.v1"},
        "--edl": {"schema_version": "audiovisual-edl.v1"},
        "--storyboard": {"schema_version": "video-storyboard.v1"},
        "--signal-report": {"schema_version": "audiovisual-bundle-signal-report.v1"},
    }
    args = []
    for option, value in values.items():
        path = tmp_path / (option[2:] + ".json")
        path.write_text(json.dumps(value), encoding="utf-8")
        args.extend([option, str(path)])
    return args


def test_cli_exports_review_and_creator_feedback_separately(tmp_path, monkeypatch, capsys):
    review = {
        "schema_version": "integrated-audiovisual-review.v1",
        "status": "REVIEW_REQUIRED",
        "findings": [{
            "severity": "warning",
            "code": "dialogue_mix_conflict",
            "message": "SC01: dialogue mix review",
        }],
        "signal_alignment": {"scenes": [{
            "scene_id": "SC01",
            "intended_energy": "low",
            "measured_audio_rms_dbfs": -22.0,
            "measured_audio_spectral_centroid_hz": 1300.0,
            "measured_video_luma": 90.0,
            "measured_video_frame_change_luma": 1.0,
            "audio_samples_available": True,
            "video_samples_available": True,
        }]},
        "publication_authorized": False,
        "assets_modified": False,
    }
    monkeypatch.setattr(cli, "review_audiovisual_production", lambda *args: review)
    review_path = tmp_path / "review.json"
    feedback_path = tmp_path / "feedback.json"

    args = _inputs(tmp_path) + [
        "--output", str(review_path),
        "--feedback-output", str(feedback_path),
    ]
    assert cli.main(args) == 0
    assert capsys.readouterr().out == ""
    assert json.loads(review_path.read_text(encoding="utf-8")) == review
    feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
    assert feedback["schema_version"] == "audiovisual-creator-feedback.v1"
    assert feedback["proposal_count"] == 1
    assert feedback["execution_policy"]["automatic_asset_changes"] is False
    assert feedback["execution_policy"]["publication_authorized"] is False
