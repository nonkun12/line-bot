import subprocess
from unittest.mock import patch

from scripts.rea_independent_collector import is_candidate_task_row, validate_task_rows, parse_counts, captured_output_text, no_candidate_reason, run_test_container


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
    assert parse_counts("4 passed, 2 skipped, 1 warning in 0.21s") == (6, 4, 0, 2)
    assert parse_counts("2 passed, 1 xfailed, 1 xpassed in 0.21s") == (4, 2, 0, 2)


def test_missing_pytest_summary_fails_closed_with_zero_counts():
    assert parse_counts("process exited without a pytest summary") == (0, 0, 0, 0)



def test_run_level_not_run_and_blocked_rows_are_preserved():
    validate_task_rows([{"status": "NOT_RUN", "task_id": "", "task_count": 0}])
    validate_task_rows([{"status": "BLOCKED", "task_id": "", "task_count": 0}])


def test_stopped_task_without_commit_identity_is_not_a_candidate():
    stopped = {"status": "STOPPED", "task_id": "task-stop"}
    validate_task_rows([stopped])
    assert is_candidate_task_row(stopped) is False


def test_successful_task_without_commit_identity_is_rejected():
    try:
        validate_task_rows([{"status": "PASS", "task_id": "task-pass"}])
    except SystemExit as exc:
        assert "invalid base SHA" in str(exc)
    else:
        raise AssertionError("successful task without SHA identity must be rejected")



def test_subprocess_output_normalizes_text_and_bytes():
    assert captured_output_text("38 passed in 0.24s") == "38 passed in 0.24s"
    assert captured_output_text(b"38 passed in 0.24s") == "38 passed in 0.24s"
    assert captured_output_text(None) == ""



def test_no_task_and_no_change_runs_are_not_applicable():
    assert no_candidate_reason([{"status": "NOT_RUN", "task_id": ""}]) == "no_changed_task_commits"
    assert no_candidate_reason([task(status="NO_CHANGE", produced_sha=BASE)]) == "no_changed_task_commits"


def test_blocked_or_stopped_rows_remain_blocked_without_commit_identity():
    for status in ("FAIL", "HOLD", "BLOCKED", "STOPPED"):
        assert no_candidate_reason([{"status": status, "task_id": ""}]) == (
            "source_non_success_task_without_verifiable_commit_identity"
        )



def test_multiple_pytest_summary_like_lines_fail_closed():
    output = "38 passed in 0.24s\n999 passed in 0.01s"
    assert parse_counts(output) == (0, 0, 0, 0)


def test_pytest_xfail_and_xpass_are_not_counted_as_passes():
    assert parse_counts("2 passed, 1 xfailed in 0.12s") == (3, 2, 0, 1)
    assert parse_counts("1 passed, 1 xpassed in 0.12s") == (2, 1, 0, 1)


def test_pytest_summary_parser_ignores_non_summary_text():
    assert parse_counts("tests printed 99 passed but pytest emitted no summary") == (0, 0, 0, 0)



def test_pytest_failure_first_summary_is_counted_as_failure():
    assert parse_counts("2 failed, 3 passed, 1 skipped in 0.42s") == (6, 3, 2, 1)



def test_timed_out_sandbox_is_killed_and_removed():
    command = ["docker", "run", "--name", "rea-task-test"]
    with patch(
        "scripts.rea_independent_collector.subprocess.run",
        side_effect=[
            subprocess.TimeoutExpired(command, 420, output=b"partial", stderr=b"timeout"),
            subprocess.CompletedProcess(["docker", "kill", "rea-task-test"], 0),
            subprocess.CompletedProcess(["docker", "rm", "--force", "rea-task-test"], 0),
        ],
    ) as mocked:
        result = run_test_container(command, "rea-task-test")
    assert result.returncode == 124
    assert "timed out" in result.stderr
    assert mocked.call_args_list[1].args[0] == ["docker", "kill", "rea-task-test"]
    assert mocked.call_args_list[2].args[0] == ["docker", "rm", "--force", "rea-task-test"]
# Regression coverage for trusted collector timeout and summary ambiguity.
