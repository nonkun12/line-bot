import json
from scripts import analyze_audiovisual_bundle as cli


def test_cli_writes_report(tmp_path, monkeypatch):
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps({"schema_version": "video-scenario.v1"}), encoding="utf-8")
    output_path = tmp_path / "report.json"
    monkeypatch.setattr(cli, "analyze_audiovisual_bundle", lambda *args: {
        "schema_version": "audiovisual-bundle-signal-report.v1",
        "publication_authorized": False,
        "assets_modified": False,
    })
    result = cli.main([
        "--scenario", str(scenario_path),
        "--audio", str(tmp_path / "draft.wav"),
        "--video", str(tmp_path / "draft.mp4"),
        "--output", str(output_path),
    ])
    assert result == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["publication_authorized"] is False
    assert report["assets_modified"] is False


def test_cli_returns_error_for_invalid_json(tmp_path, capsys):
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text("{", encoding="utf-8")
    result = cli.main([
        "--scenario", str(scenario_path),
        "--audio", str(tmp_path / "draft.wav"),
        "--video", str(tmp_path / "draft.mp4"),
    ])
    assert result == 2
    assert "analysis failed:" in capsys.readouterr().err
