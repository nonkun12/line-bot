from __future__ import annotations

import copy
import json
import sys

import pytest

from scripts.recovery_hold_diagnostics import analyze_recovery_holds, main


def _state():
    return {
        "version": 1,
        "completed": ["task-done"],
        "recovery_ai": {
            "schema_version": 1,
            "checkpoint": None,
            "tasks": {
                "task-nonrepairable": {
                    "held": True,
                    "hold_reason": "non_repairable_failure",
                    "hold_category": "invalid_task",
                    "consecutive_failures": 1,
                    "same_fingerprint_attempts": 1,
                    "updated_at": "2026-11-03T06:42:16+00:00",
                    "last_decision_action": "HOLD",
                },
                "task-budget": {
                    "held": True,
                    "hold_reason": "repair_budget_exhausted",
                    "hold_category": "unknown",
                    "consecutive_failures": 2,
                    "same_fingerprint_attempts": 2,
                },
                "task-review": {
                    "held": False,
                    "resume_requires_review": True,
                },
                "task-ready": {
                    "held": False,
                    "resume_requires_review": False,
                },
            },
        },
    }


def _catalog():
    return {"tasks": [
        {"id": "task-nonrepairable", "execution_approved": True},
        {"id": "task-budget", "execution_approved": True},
        {"id": "task-review", "execution_approved": True},
        {"id": "task-ready", "execution_approved": True},
        {"id": "task-done", "execution_approved": True},
        {"id": "task-unapproved", "execution_approved": False},
    ]}


def test_diagnostics_report_holds_and_evidence_without_granting_authority():
    state = _state()
    before = copy.deepcopy(state)
    result = analyze_recovery_holds(state, _catalog())

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["mode"] == "READ_ONLY"
    assert result["held_count"] == 2
    assert result["resume_review_pending_count"] == 1
    assert result["approved_held_count"] == 2
    assert result["eligible_approved_task_count"] == 1
    assert result["execution_authorized"] is False
    assert result["hold_clear_authorized"] is False
    assert result["task_resume_authorized"] is False
    by_id = {item["task_id"]: item for item in result["diagnostics"]}
    assert by_id["task-nonrepairable"]["next_step"] == (
        "review_original_failure_and_collect_fresh_evidence_before_any_resume"
    )
    assert "independent_rea_verification" in by_id["task-budget"]["required_evidence"]
    assert by_id["task-review"]["next_step"] == "complete_post_resume_review_without_running_the_task"
    assert state == before


def test_diagnostics_do_not_treat_unapproved_or_completed_tasks_as_eligible():
    state = _state()
    state["recovery_ai"]["tasks"]["task-unapproved"] = {"held": False}
    state["recovery_ai"]["tasks"]["task-done"] = {"held": False}
    result = analyze_recovery_holds(state, _catalog())
    assert result["eligible_approved_task_count"] == 1


def test_diagnostics_fail_closed_on_duplicate_catalog_ids():
    catalog = _catalog()
    catalog["tasks"].append({"id": "task-ready", "execution_approved": True})
    with pytest.raises(ValueError, match="duplicate catalog"):
        analyze_recovery_holds(_state(), catalog)


def test_diagnostics_fail_closed_on_ambiguous_recovery_flags():
    state = _state()
    state["recovery_ai"]["tasks"]["task-ready"]["held"] = "false"
    with pytest.raises(ValueError, match="flags ambiguous"):
        analyze_recovery_holds(state, _catalog())


def test_diagnostics_fail_closed_on_invalid_checkpoint():
    state = _state()
    state["recovery_ai"]["checkpoint"] = {"verified": False}
    with pytest.raises(ValueError, match="checkpoint is ambiguous"):
        analyze_recovery_holds(state, _catalog())


def test_diagnostics_fail_closed_on_invalid_catalog_approval_type():
    catalog = _catalog()
    catalog["tasks"][0]["execution_approved"] = "true"
    with pytest.raises(ValueError, match="approval must be boolean"):
        analyze_recovery_holds(_state(), catalog)


def test_cli_emits_read_only_diagnostics_without_mutating_inputs(tmp_path, monkeypatch, capsys):
    state_path = tmp_path / "state.json"
    catalog_path = tmp_path / "catalog.json"
    state_path.write_text(json.dumps(_state()), encoding="utf-8")
    catalog_path.write_text(json.dumps(_catalog()), encoding="utf-8")
    state_before = state_path.read_bytes()
    catalog_before = catalog_path.read_bytes()
    monkeypatch.setattr(sys, "argv", [
        "recovery_hold_diagnostics.py",
        "--state-file", str(state_path),
        "--catalog", str(catalog_path),
    ])

    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "READ_ONLY"
    assert output["status"] == "REVIEW_REQUIRED"
    assert output["task_resume_authorized"] is False
    assert state_path.read_bytes() == state_before
    assert catalog_path.read_bytes() == catalog_before


def test_cli_returns_blocked_for_malformed_state_without_mutation(tmp_path, monkeypatch, capsys):
    state_path = tmp_path / "state.json"
    catalog_path = tmp_path / "catalog.json"
    state_path.write_text("{broken", encoding="utf-8")
    catalog_path.write_text(json.dumps(_catalog()), encoding="utf-8")
    state_before = state_path.read_bytes()
    monkeypatch.setattr(sys, "argv", [
        "recovery_hold_diagnostics.py",
        "--state-file", str(state_path),
        "--catalog", str(catalog_path),
    ])

    assert main() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "BLOCKED"
    assert output["execution_authorized"] is False
    assert state_path.read_bytes() == state_before
