from datetime import datetime, timezone

import pytest

from scripts.distributed_loop_budget_gate import calculate_used_minutes, evaluate_budget


NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def test_budget_counts_started_jobs_with_per_job_minute_rounding():
    jobs = [
        {"started_at": "2026-11-15T11:00:00Z", "completed_at": "2026-11-15T11:00:01Z"},
        {"started_at": "2026-11-15T11:00:00Z", "completed_at": "2026-11-15T11:01:00Z"},
        {"started_at": "2026-11-15T11:59:00Z", "completed_at": None},
        {"started_at": None, "completed_at": None},
    ]
    assert calculate_used_minutes(jobs, now=NOW) == 3


def test_budget_ignores_job_time_before_current_utc_month():
    jobs = [
        {"started_at": "2026-10-31T23:58:00Z", "completed_at": "2026-11-01T00:02:00Z"},
    ]
    assert calculate_used_minutes(jobs, now=NOW) == 2


def test_budget_blocks_at_or_above_limit():
    jobs = [
        {"started_at": "2026-11-15T11:00:00Z", "completed_at": "2026-11-15T11:10:00Z"},
    ]
    result = evaluate_budget(jobs, budget_minutes=10, now=NOW)
    assert result["allowed"] is False
    assert result["reason"] == "repository_budget_exhausted"


def test_budget_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="timezone"):
        calculate_used_minutes(
            [{"started_at": "2026-11-15T11:00:00", "completed_at": None}],
            now=NOW,
        )


def test_budget_rejects_boolean_limit():
    with pytest.raises(ValueError, match="integer"):
        evaluate_budget([], budget_minutes=True, now=NOW)
