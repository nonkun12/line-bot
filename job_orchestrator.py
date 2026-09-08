"""Persistent Job lifecycle decisions for the overnight development worker.

The orchestrator owns retry policy; LangGraph owns the bounded node sequence.
Keeping this policy outside the graph prevents a long-running self-loop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryDecision:
    retry_count: int
    retry: bool
    terminal_status: str
    reason: str


def decide_test_failure(job: dict) -> RetryDecision:
    """Consume one retry budget after a failed automated test."""
    retry_count = int(job.get("retry_count") or 0) + 1
    max_retries = max(0, int(job.get("max_retries") or 0))

    if retry_count <= max_retries:
        return RetryDecision(
            retry_count=retry_count,
            retry=True,
            terminal_status="pending",
            reason="automated test failed; retry through Debug -> Fix -> Patch -> Test",
        )

    return RetryDecision(
        retry_count=retry_count,
        retry=False,
        terminal_status="failed",
        reason="automated test failed; retry limit reached",
    )


def decide_executor_failure(job: dict) -> RetryDecision:
    """Consume one retry budget after an unexpected worker/executor error."""
    retry_count = int(job.get("retry_count") or 0) + 1
    max_retries = max(0, int(job.get("max_retries") or 0))

    if retry_count <= max_retries:
        return RetryDecision(
            retry_count=retry_count,
            retry=True,
            terminal_status="pending",
            reason="worker execution failed; retry scheduled",
        )

    return RetryDecision(
        retry_count=retry_count,
        retry=False,
        terminal_status="failed",
        reason="worker execution failed; retry limit reached",
    )
