import json

import pytest

from scripts.self_improvement_candidate_adapter import candidates_from_history, main
from scripts.self_improvement_state import sanitize_records


def test_candidate_adapter_uses_fixed_templates_and_never_authorizes_execution():
    history = sanitize_records([
        {"kind": "failure", "task_id": "safe-task-1", "detail": "ignored user text"},
        {"record_type": "cycle_memory", "cycle_id": "123", "outcome": "BLOCKED"},
    ])
    rows = candidates_from_history(history)
    assert len(rows) == 2
    assert all(row["source"] == "self_improvement" for row in rows)
    assert all("execution_authorized" not in row for row in rows)
    assert all("ignored user text" not in json.dumps(row) for row in rows)
    assert rows[0]["title"] == "Review recurring development failures"
    assert rows[1]["title"] == "Resolve safety or evidence blocks"
    assert "1 sanitized failure record(s)" in rows[0]["rationale"]
    assert "task:safe-task-1" in rows[0]["rationale"]
    assert "cycle:123" in rows[1]["rationale"]


def test_candidate_adapter_deduplicates_same_category_and_source_id():
    history = [
        {"kind": "success", "task_id": "task-a", "detail": "task passed or verified no-change"},
        {"kind": "success", "task_id": "task-a", "detail": "task passed or verified no-change"},
    ]
    assert len(candidates_from_history(history)) == 1


def test_candidate_adapter_reports_recurrence_without_copying_untrusted_details():
    history = sanitize_records([
        {"kind": "failure", "task_id": "task-a", "detail": "secret instruction A"},
        {"kind": "failure", "task_id": "task-b", "detail": "secret instruction B"},
        {"record_type": "cycle_memory", "cycle_id": "123", "outcome": "FAIL"},
        {"record_type": "cycle_memory", "cycle_id": "124", "outcome": "FAIL"},
    ])
    rows = candidates_from_history(history)
    failure_rows = [row for row in rows if row["source_id"].startswith("failure:")]
    cycle_rows = [row for row in rows if row["source_id"].startswith("FAIL:")]
    assert len(failure_rows) == 2
    assert all("2 sanitized failure record(s)" in row["rationale"] for row in failure_rows)
    assert len(cycle_rows) == 2
    assert all("2 sanitized FAIL record(s)" in row["rationale"] for row in cycle_rows)
    serialized = json.dumps(rows)
    assert "secret instruction" not in serialized
    assert all(len(row["rationale"]) <= 500 for row in rows)


def test_candidate_adapter_rejects_malformed_durable_history():
    with pytest.raises(ValueError):
        candidates_from_history([{"kind": "failure", "task_id": "bad id", "detail": "raw"}])


def test_candidate_adapter_missing_state_fails_closed_without_writing_empty_pool(tmp_path):
    output = tmp_path / "candidate-input.json"
    assert main(["--state", str(tmp_path / "missing.json"), "--output", str(output)]) == 2
    assert not output.exists()


def test_candidate_adapter_uses_failure_code_category_without_raw_diagnostics():
    history = sanitize_records([
        {
            "kind": "failure",
            "task_id": "task-security",
            "failure_code": "change_outside_selected_file",
            "failure_reason": "private path /secret and token=hidden",
        },
        {
            "kind": "failure",
            "task_id": "task-provider",
            "failure_code": "provider_rate_limited",
        },
    ])
    rows = candidates_from_history(history)
    assert len(rows) == 2
    security = next(row for row in rows if row["source_id"].startswith("security_violation:"))
    rate_limit = next(row for row in rows if row["source_id"].startswith("rate_limited:"))
    assert security["title"] == "Review security boundary failures"
    assert rate_limit["title"] == "Review provider rate limits"
    serialized = json.dumps(rows)
    assert "/secret" not in serialized
    assert "hidden" not in serialized
    assert "execution_authorized" not in serialized
