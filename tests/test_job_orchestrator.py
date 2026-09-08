from job_orchestrator import decide_executor_failure, decide_test_failure


def test_test_failure_schedules_retry_until_budget_is_exhausted():
    assert decide_test_failure({"retry_count": 0, "max_retries": 2}).retry is True
    decision = decide_test_failure({"retry_count": 2, "max_retries": 2})
    assert decision.retry is False
    assert decision.retry_count == 3
    assert decision.terminal_status == "failed"


def test_executor_failure_uses_same_bounded_budget():
    decision = decide_executor_failure({"retry_count": 1, "max_retries": 2})
    assert decision.retry is True
    assert decision.retry_count == 2
    assert decision.terminal_status == "pending"


def test_negative_or_missing_budget_cannot_create_an_infinite_retry_loop():
    decision = decide_test_failure({"retry_count": 0, "max_retries": 0})
    assert decision.retry is False
    assert decision.terminal_status == "failed"
