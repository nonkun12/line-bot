from scripts.rea_independent_collector import is_candidate_task_row, validate_task_rows, parse_counts


BASE = "1" * 40
HEAD = "2" * 40


def task(**overrides):
    row = {
        "task_id": "task-001",
        "status": "PASS",
        "base_sha": BASE,
        "produced_sha": HEAD,
    }
    row.update(overrides)
    return row


def test_changed_success_task_is_collected():
    assert is_candidate_task_row(task()) is True


def test_failed_task_is_not_silently_dropped_even_without_commit():
    assert is_candidate_task_row(
        task(status="FAIL", produced_sha=BASE)
    ) is True


def test_held_or_blocked_task_is_preserved():
    assert is_candidate_task_row(
        task(status="HOLD", produced_sha=BASE)
    ) is True
    assert is_candidate_task_row(
        task(status="BLOCKED", produced_sha=BASE)
    ) is True


def test_successful_no_change_task_needs_no_test_run():
    assert is_candidate_task_row(
        task(status="NO_CHANGE", produced_sha=BASE)
    ) is False


def test_malformed_task_identity_is_rejected():
    assert is_candidate_task_row(task(task_id="")) is False
    assert is_candidate_task_row(task(base_sha="bad")) is False
    assert is_candidate_task_row(task(produced_sha="bad")) is False
    assert is_candidate_task_row(None) is False



def test_task_rows_require_unique_ids_and_supported_statuses():
    validate_task_rows([task()])
    try:
        validate_task_rows([task(), task()])
    except SystemExit as exc:
        assert "not unique" in str(exc)
    else:
        raise AssertionError("duplicate task IDs must be rejected")

    try:
        validate_task_rows([task(status="UNKNOWN")])
    except SystemExit as exc:
        assert "unsupported status" in str(exc)
    else:
        raise AssertionError("unsupported task status must be rejected")


def test_task_rows_are_bounded_to_four():
    validate_task_rows([task(task_id=f"task-{index}") for index in range(4)])
    try:
        validate_task_rows([task(task_id=f"task-{index}") for index in range(5)])
    except SystemExit as exc:
        assert "count" in str(exc)
    else:
        raise AssertionError("more than four tasks must be rejected")



def test_pytest_summary_counts_are_parsed_from_captured_output():
    assert parse_counts("33 passed in 0.16s") == (33, 33, 0, 0)
    assert parse_counts("4 passed, 2 skipped in 0.21s") == (6, 4, 0, 2)
    assert parse_counts("3 passed, 1 failed in 0.30s") == (4, 3, 1, 0)


def test_missing_pytest_summary_fails_closed_with_zero_counts():
    assert parse_counts("process exited without a pytest summary") == (0, 0, 0, 0)
