import json

from scripts.create_audiovisual_bundle import main


def test_cli_creates_bundle_from_scenario_json(tmp_path, capsys):
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps({
        "schema_version": "video-scenario.v1",
        "status": "draft",
        "title": "unused",
    }), encoding="utf-8")
    # The scenario validator rejects this incomplete object before touching output.
    output = tmp_path / "bundle"
    assert main([str(scenario_path), str(output)]) == 2
    assert not output.exists()
    captured = capsys.readouterr()
    assert '"status": "failed"' in captured.err


def test_cli_requires_a_new_output_directory(tmp_path, capsys):
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    assert main([str(scenario_path), str(output)]) == 2
    assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"
