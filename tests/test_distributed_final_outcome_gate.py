from __future__ import annotations

import json

import pytest

from scripts.enforce_distributed_final_outcome import main, validate_final_outcome


@pytest.mark.parametrize("outcome", ["COMPLETED", "NOT_RUN"])
def test_only_completed_or_explicit_queue_empty_not_run_are_success(outcome):
    assert validate_final_outcome({"schema_version": 1, "outcome": outcome}) == (True, outcome)


@pytest.mark.parametrize("outcome", ["BLOCKED", "FAILED", "INCOMPLETE"])
def test_non_success_outcomes_fail_closed(outcome):
    allowed, reason = validate_final_outcome({"schema_version": 1, "outcome": outcome})
    assert allowed is False
    assert reason == f"outcome_{outcome.lower()}"


@pytest.mark.parametrize(
    "payload",
    [
        None, [], {}, {"schema_version": 2, "outcome": "COMPLETED"},
        {"schema_version": True, "outcome": "COMPLETED"},
        {"schema_version": 1, "outcome": ""},
        {"schema_version": 1, "outcome": "SUCCESS"},
        {"schema_version": 1, "outcome": 0},
    ],
)
def test_malformed_missing_or_unknown_outcome_fails_closed(payload):
    assert validate_final_outcome(payload)[0] is False


def test_main_fails_when_input_file_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["enforce_distributed_final_outcome", "--input", str(tmp_path / "missing.json")])
    assert main() == 1
    assert "failing closed" in capsys.readouterr().out


def test_main_fails_on_invalid_json(tmp_path, monkeypatch):
    report = tmp_path / "outcome.json"
    report.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["enforce_distributed_final_outcome", "--input", str(report)])
    assert main() == 1


def test_main_accepts_not_run_machine_readable_record(tmp_path, monkeypatch, capsys):
    report = tmp_path / "outcome.json"
    report.write_text(json.dumps({"schema_version": 1, "outcome": "NOT_RUN"}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["enforce_distributed_final_outcome", "--input", str(report)])
    assert main() == 0
    assert "NOT_RUN" in capsys.readouterr().out
