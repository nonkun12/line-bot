from datetime import datetime, timedelta, timezone

import job_orchestrator


def test_test_failure_retries_until_limit():
    job = {"retry_count": 0, "max_retries": 2}

    first = job_orchestrator.decide_test_failure(job)
    assert first.retry is True
    assert first.retry_count == 1
    assert first.terminal_status == "pending"

    second_job = {**job, "retry_count": first.retry_count}
    second = job_orchestrator.decide_test_failure(second_job)
    assert second.retry is True
    assert second.retry_count == 2
    assert second.terminal_status == "pending"

    final_job = {**job, "retry_count": second.retry_count}
    final = job_orchestrator.decide_test_failure(final_job)
    assert final.retry is False
    assert final.retry_count == 3
    assert final.terminal_status == "failed"


def test_executor_failure_uses_same_bounded_retry_policy():
    job = {"retry_count": 1, "max_retries": 1}
    decision = job_orchestrator.decide_executor_failure(job)

    assert decision.retry is False
    assert decision.retry_count == 2
    assert decision.terminal_status == "failed"
    assert "retry limit" in decision.reason


def test_zero_max_retries_fails_first_failure():
    job = {"retry_count": 0, "max_retries": 0}
    decision = job_orchestrator.decide_test_failure(job)

    assert decision.retry is False
    assert decision.retry_count == 1
    assert decision.terminal_status == "failed"


def test_deploy_failure_has_strict_single_retry_budget():
    first = job_orchestrator.decide_deploy_failure({"retry_count": 0})
    assert first.retry is True
    assert first.retry_count == 1
    assert first.terminal_status == "pending"

    second = job_orchestrator.decide_deploy_failure({"retry_count": first.retry_count})
    assert second.retry is False
    assert second.retry_count == 2
    assert second.terminal_status == "failed"
    assert "deploy retry limit" in second.reason


def test_job_time_limit_detects_expired_job():
    now = datetime.now(timezone.utc)
    job = {"created_at": (now - timedelta(seconds=61)).isoformat()}
    assert job_orchestrator.job_time_exceeded(job, now=now, max_seconds=60) is True


def test_job_time_limit_allows_job_within_budget():
    now = datetime.now(timezone.utc)
    job = {"created_at": (now - timedelta(seconds=59)).isoformat()}
    assert job_orchestrator.job_time_exceeded(job, now=now, max_seconds=60) is False


def test_no_progress_detects_same_failure_after_patch_cycle():
    previous = '{"test_result": {"passed": false, "error": "AssertionError: expected 42, got 41"}}'
    current = '{"test_result": {"passed": false, "error": "AssertionError: expected 42, got 41"}}'
    assert job_orchestrator.test_failure_has_no_progress(previous, current) is True


def test_no_progress_allows_changed_failure():
    previous = '{"test_result": {"passed": false, "error": "AssertionError: expected 42, got 41"}}'
    current = '{"test_result": {"passed": false, "error": "AssertionError: expected 42, got 40"}}'
    assert job_orchestrator.test_failure_has_no_progress(previous, current) is False
