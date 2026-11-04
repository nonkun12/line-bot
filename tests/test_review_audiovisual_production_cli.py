import json

from scripts import review_audiovisual_production as cli


def _write_inputs(tmp_path):
    paths = {}
    for option, filename in (
        ("--scenario", "scenario.json"),
        ("--music-plan", "music.json"),
        ("--edl", "edl.json"),
        ("--storyboard", "storyboard.json"),
        ("--signal-report", "signals.json"),
    ):
        path = tmp_path / filename
        path.write_text(json.dumps({"kind": filename}), encoding="utf-8")
        paths[option] = path
    args = []
    for option, path in paths.items():
        args.extend([option, str(path)])
    return args


def test_cli_writes_integrated_report_to_output_file(tmp_path, monkeypatch):
    captured = []
    expected = {
        "schema_version": "integrated-audiovisual-review.v1",
        "publication_authorized": False,
        "assets_modified": False,
    }

    def fake_review(scenario, music, edl, storyboard, signals):
        captured.extend([scenario, music, edl, storyboard, signals])
        return expected

    monkeypatch.setattr(cli, "review_audiovisual_production", fake_review)
    output = tmp_path / "review.json"
    args = _write_inputs(tmp_path) + ["--output", str(output)]

    assert cli.main(args) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == expected
    assert len(captured) == 5
    assert all(isinstance(item, dict) for item in captured)


def test_cli_prints_report_to_stdout_when_output_is_omitted(tmp_path, monkeypatch, capsys):
    expected = {"status": "REVIEW_REQUIRED", "publication_authorized": False}
    monkeypatch.setattr(cli, "review_audiovisual_production", lambda *args: expected)

    assert cli.main(_write_inputs(tmp_path)) == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_cli_fails_closed_for_non_object_json(tmp_path, capsys):
    args = _write_inputs(tmp_path)
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text("[]", encoding="utf-8")
    args[1] = str(scenario_path)

    assert cli.main(args) == 2
    assert "scenario JSON root must be an object" in capsys.readouterr().err
