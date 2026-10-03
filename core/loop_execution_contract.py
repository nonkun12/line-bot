"""Immutable execution contract for distributed AI Loop task evidence.

This module is deliberately side-effect free. It defines the minimum evidence
that must exist before a loop result can be treated as integration-ready.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class ExecutionEvidence:
    task_id: str
    loop_id: str
    base_sha: str
    result: ExecutionResult
    produced_sha: str | None
    tests_passed: bool
    verified: bool
    safety_gate_passed: bool
    actual_changes: tuple[str, ...] = ()
    error: str | None = None
    sheets_write_result: str | None = None

    def __post_init__(self) -> None:
        if not self.task_id or not self.loop_id:
            raise ValueError("task_id and loop_id are required")
        if not self.base_sha:
            raise ValueError("base_sha is required")
        if self.result is ExecutionResult.PASS:
            if not self.produced_sha:
                raise ValueError("PASS requires produced_sha")
            if not self.tests_passed or not self.verified or not self.safety_gate_passed:
                raise ValueError("PASS requires tests, verification, and safety gate")
        if self.result is not ExecutionResult.PASS and self.produced_sha and not self.tests_passed:
            # A produced SHA on failure is allowed only when the failed run records
            # the exact non-passing state; callers must not interpret it as safe.
            return

    def as_audit_row(self) -> dict[str, object]:
        """Return stable column-oriented evidence suitable for Sheets/audit sinks."""
        return {
            "task_id": self.task_id,
            "loop_id": self.loop_id,
            "base_sha": self.base_sha,
            "result": self.result.value,
            "produced_sha": self.produced_sha or "",
            "tests_passed": self.tests_passed,
            "verified": self.verified,
            "safety_gate_passed": self.safety_gate_passed,
            "actual_changes": "\n".join(self.actual_changes),
            "error": self.error or "",
            "sheets_write_result": self.sheets_write_result or "",
        }


def integration_ready(evidence: ExecutionEvidence) -> bool:
    """Integration is permitted only after all independent gates pass."""
    return (
        evidence.result is ExecutionResult.PASS
        and bool(evidence.produced_sha)
        and evidence.tests_passed
        and evidence.verified
        and evidence.safety_gate_passed
    )
