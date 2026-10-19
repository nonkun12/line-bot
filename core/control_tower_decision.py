"""Provider-neutral, non-authoritative Control Tower decision contract.

This record captures a bounded recommendation. It contains no executable
instruction and never grants repository mutation, merge, or deploy rights.
Callers must independently validate the evidence SHA and registered task ID.
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
import math
import re


VALID_GATE_STATUSES = frozenset({"PASS", "BLOCKED", "NOT_RUN"})
VALID_NEXT_ACTIONS = frozenset({
    "OBSERVE_ONLY",
    "SELECT_REGISTERED_TASK",
    "HOLD",
    "NOT_RUN",
})
VALID_REASON_CODES = frozenset({
    "evidence_sufficient",
    "reviewer_unavailable",
    "queue_empty",
    "task_held",
    "duplicate_task",
    "invalid_state",
    "policy_blocked",
    "test_failure",
    "retry_budget_exhausted",
    "recurring_failure",
})
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TASK_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


@dataclass(frozen=True)
class ControlTowerDecisionRecord:
    """A validated recommendation that downstream policy must still authorize."""

    reason_code: str
    confidence: float
    priority: int
    next_action: str
    gate_status: str
    evidence_sha: str | None = None
    task_template_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, str) or self.reason_code not in VALID_REASON_CODES:
            raise ValueError("reason_code is not allowlisted")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise ValueError("confidence must be numeric")
        if not math.isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be finite and between 0 and 1")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int) or not 0 <= self.priority <= 100:
            raise ValueError("priority must be an integer between 0 and 100")
        if not isinstance(self.next_action, str) or self.next_action not in VALID_NEXT_ACTIONS:
            raise ValueError("next_action is not allowlisted")
        if not isinstance(self.gate_status, str) or self.gate_status not in VALID_GATE_STATUSES:
            raise ValueError("gate_status is not allowlisted")
        if self.evidence_sha is not None:
            if not isinstance(self.evidence_sha, str) or not _SHA_RE.fullmatch(self.evidence_sha):
                raise ValueError("evidence_sha must be a 40-character lowercase SHA")
        if self.task_template_id is not None:
            if not isinstance(self.task_template_id, str) or not _TASK_ID_RE.fullmatch(self.task_template_id):
                raise ValueError("task_template_id is invalid")
        if self.next_action == "SELECT_REGISTERED_TASK":
            if self.gate_status != "PASS":
                raise ValueError("task selection requires a PASS gate")
            if self.evidence_sha is None:
                raise ValueError("task selection requires source evidence SHA")
            if self.task_template_id is None:
                raise ValueError("task selection requires a registered template ID")
        elif self.task_template_id is not None:
            raise ValueError("only task selection may name a task template")

    def execution_eligible(
        self,
        registered_task_ids: Collection[str],
        current_head_sha: str,
    ) -> bool:
        """Return whether policy may consider this task; never executes it.

        Exact registry membership and an exact match to the observed HEAD are
        mandatory. Invalid caller inputs fail closed rather than raising.
        """
        if not isinstance(registered_task_ids, Collection) or isinstance(
            registered_task_ids, (str, bytes)
        ):
            return False
        if not isinstance(current_head_sha, str) or not _SHA_RE.fullmatch(current_head_sha):
            return False
        return (
            self.next_action == "SELECT_REGISTERED_TASK"
            and self.gate_status == "PASS"
            and self.evidence_sha == current_head_sha
            and self.task_template_id is not None
            and self.task_template_id in registered_task_ids
        )

    def is_high_priority(self) -> bool:
        """Return True if priority is considered high (>=80)."""
        return self.priority >= 80


__all__ = [
    "ControlTowerDecisionRecord",
    "VALID_GATE_STATUSES",
    "VALID_NEXT_ACTIONS",
    "VALID_REASON_CODES",
]
