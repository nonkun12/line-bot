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



def test_import_export_round_trip_is_sanitized_and_does_not_duplicate(tmp_path):
    from scripts.self_improvement_state import main
    import sys

    state = tmp_path / "state.json"
    history = tmp_path / "history.jsonl"
    state.write_text(json.dumps({
        "version": 1,
        "completed": [],
        "self_improvement_history": [{
            "kind": "failure",
            "task_id": "task-1",
            "detail": "old token=secret",
        }],
    }), encoding="utf-8")

    original_argv = sys.argv
    try:
        sys.argv = ["self_improvement_state.py", "import", "--state", str(state), "--history", str(history)]
        assert main() == 0
        with history.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "kind": "repair",
                "task_id": "task-2",
                "detail": "raw exception with private data",
            }) + "\n")
        sys.argv = ["self_improvement_state.py", "export", "--state", str(state), "--history", str(history)]
        assert main() == 0
    finally:
        sys.argv = original_argv

    persisted = json.loads(state.read_text(encoding="utf-8"))["self_improvement_history"]
    assert persisted == [
        {"kind": "failure", "task_id": "task-1", "detail": "development failure observed"},
        {"kind": "repair", "task_id": "task-2", "detail": "development required repair attempts"},
    ]
    assert "secret" not in json.dumps(persisted)
    assert "private data" not in json.dumps(persisted)



def test_loop_results_are_mapped_to_registered_task_ids_and_sanitized(tmp_path):
    from scripts.self_improvement_state import append_loop_results

    history = tmp_path / "history.jsonl"
    results = tmp_path / "results.jsonl"
    history.write_text(json.dumps({"kind": "repair", "task_id": "task-1", "detail": "raw token=secret"}) + "\n", encoding="utf-8")
    results.write_text("\n".join([
        json.dumps({"status": "PASS", "task_id": "catalog-task-1", "failure_reason": "must not persist secret=abc"}),
        json.dumps({"status": "NO_CHANGE", "task_id": "catalog-task-2"}),
        json.dumps({"status": "FAIL", "task_id": "catalog-task-3", "failure_reason": "private traceback"}),
        json.dumps({"status": "BLOCKED", "task_id": "catalog-task-4"}),
        json.dumps({"status": "PASS", "task_id": "../unsafe"}),
    ]) + "\n", encoding="utf-8")

    assert append_loop_results(history, results) == 3
    rows = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {"kind": "repair", "task_id": "task-1", "detail": "development required repair attempts"},
        {"kind": "success", "task_id": "catalog-task-1", "detail": "development reached integration gate"},
        {"kind": "success", "task_id": "catalog-task-2", "detail": "development reached integration gate"},
        {"kind": "failure", "task_id": "catalog-task-3", "detail": "development failure observed"},
    ]
    assert "secret" not in json.dumps(rows)
    assert "traceback" not in json.dumps(rows)


def test_append_loop_results_cli_requires_results_file(tmp_path):
    from scripts.self_improvement_state import main
    import sys

    history = tmp_path / "history.jsonl"
    original_argv = sys.argv
    try:
        sys.argv = ["self_improvement_state.py", "append-loop-results", "--history", str(history)]
        try:
            main()
        except SystemExit as exc:
            assert "--results is required" in str(exc)
        else:
            raise AssertionError("expected missing-results rejection")
    finally:
        sys.argv = original_argv
