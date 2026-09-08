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
