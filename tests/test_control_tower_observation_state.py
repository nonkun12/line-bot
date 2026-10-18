import json

import pytest

from scripts.control_tower_observation_state import main, sanitize


def _record(**overrides):
    row = {
        "timestamp": "2026-10-18T00:00:00+00:00",
        "task_id": "task-1",
        "status": "PASS",
        "exit_code": 0,
        "base_sha": "a" * 40,
        "produced_sha": "b" * 40,
        "signals": [{"kind": "failure", "task_id": "task-1", "detail": "token=secret"}],
        "proposal": {"task_hash": "c" * 64, "executable": False, "approval_required": True},
    }
    row.update(overrides)
    return row


def test_sanitizer_discards_free_text_and_keeps_proposal_non_executable():
    rows = sanitize([_record()])
    serialized = json.dumps(rows)
    assert "secret" not in serialized
    assert "token=" not in serialized
    assert rows[0]["signals"][0]["detail"] == "development failure observed"
    assert rows[0]["proposal"] == {
        "task_hash": "c" * 64,
        "executable": False,
        "approval_required": True,
    }


@pytest.mark.parametrize("overrides", [
    {"status": "PASS\nINJECT"},
    {"exit_code": False},
    {"base_sha": "not-a-sha"},
    {"task_id": "../secrets"},
    {"proposal": {"task_hash": "not-a-hash"}},
])
def test_sanitizer_rejects_malformed_evidence(overrides):
    with pytest.raises(ValueError):
        sanitize([_record(**overrides)])


def test_sanitizer_bounds_history():
    rows = [_record(task_id=f"task-{i}") for i in range(250)]
    safe = sanitize(rows)
    assert len(safe) == 200
    assert safe[0]["task_id"] == "task-50"
    assert safe[-1]["task_id"] == "task-249"


def test_sanitizer_preserves_non_executable_proposal_without_task():
    rows = sanitize([_record(proposal={"task_hash": None, "executable": False, "approval_required": True})])
    assert rows[0]["proposal"] == {
        "task_hash": None,
        "executable": False,
        "approval_required": True,
    }


def test_durable_observation_import_export_roundtrip(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    history_path = tmp_path / "history.jsonl"
    state_path.write_text(json.dumps({"other": "preserved", "control_tower_observations": [_record()]}))

    monkeypatch.setattr("sys.argv", ["control_tower_observation_state", "import", "--state", str(state_path), "--history", str(history_path)])
    assert main() == 0
    imported = [json.loads(line) for line in history_path.read_text().splitlines()]
    assert len(imported) == 1
    assert "secret" not in json.dumps(imported)

    # A subsequent run adds an observation; export must persist only sanitized records.
    with history_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(_record(task_id="task-2", status="BLOCKED", exit_code=80, proposal=None)) + "\n")
    monkeypatch.setattr("sys.argv", ["control_tower_observation_state", "export", "--state", str(state_path), "--history", str(history_path)])
    assert main() == 0
    saved = json.loads(state_path.read_text())
    assert saved["other"] == "preserved"
    assert [row["task_id"] for row in saved["control_tower_observations"]] == ["task-1", "task-2"]
    assert "secret" not in json.dumps(saved["control_tower_observations"])


def test_import_fails_closed_on_malformed_durable_history(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    history_path = tmp_path / "history.jsonl"
    state_path.write_text(json.dumps({"control_tower_observations": [_record(status="UNKNOWN")]}))
    monkeypatch.setattr("sys.argv", ["control_tower_observation_state", "import", "--state", str(state_path), "--history", str(history_path)])
    with pytest.raises(ValueError):
        main()
    assert not history_path.exists()
