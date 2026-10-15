import json

from scripts.self_improvement_state import MAX_RECORDS, sanitize_records


def test_sanitizer_discards_raw_error_text_and_unknown_fields():
    rows = sanitize_records([
        {
            "kind": "failure",
            "task_id": "uhip-test:failure",
            "detail": "token=super-secret raw exception and prompt",
            "prompt": "private input",
        },
        {"kind": "repair", "task_id": "../secrets", "detail": "raw error"},
        {"kind": "provider-call", "task_id": "safe", "detail": "unknown kind"},
    ])

    assert rows == [
        {
            "kind": "failure",
            "task_id": "uhip-test:failure",
            "detail": "development failure observed",
        },
        {
            "kind": "repair",
            "task_id": None,
            "detail": "development required repair attempts",
        },
    ]
    assert "super-secret" not in json.dumps(rows)
    assert "private input" not in json.dumps(rows)


def test_sanitizer_bounds_history_to_latest_200():
    rows = [{"kind": "success", "task_id": f"task-{i}", "detail": "anything"} for i in range(250)]
    safe = sanitize_records(rows)

    assert len(safe) == MAX_RECORDS
    assert safe[0]["task_id"] == "task-50"
    assert safe[-1]["task_id"] == "task-249"


def test_sanitizer_fails_closed_on_wrong_container():
    try:
        sanitize_records({"kind": "failure"})
    except ValueError as exc:
        assert "must be a list" in str(exc)
    else:
        raise AssertionError("expected ValueError")
