"""Explicit, advisory-only bridge from deterministic Recovery AI to local fm.

This bridge is opt-in and Mac-only. It never changes RecoveryStore state or executes
suggestions. The deterministic RecoveryDecision remains authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from scripts.recovery_ai import REPAIRABLE_CATEGORIES, RecoveryDecision
from scripts.recovery_ai_fm_advisor import AdvisorError, diagnose


@dataclass(frozen=True)
class LocalAdvisorResult:
    status: str
    task_id: str
    decision_action: str
    suggestion: dict[str, str] | None
    reason: str


def advise_for_decision(
    decision: RecoveryDecision,
    category: str,
    failing_tests: Iterable[str] = (),
    *,
    advisor: Callable[..., dict[str, str]] = diagnose,
) -> LocalAdvisorResult:
    """Ask fm for investigation ideas only when the existing controller permits repair.

    The function is opt-in, does not persist state, and never changes the decision.
    Unsupported actions/categories and advisor failures return a non-actionable status.
    """
    if not isinstance(decision, RecoveryDecision):
        raise TypeError("decision must be a RecoveryDecision")

    if decision.action != "REPAIR_ONCE":
        return LocalAdvisorResult(
            "SKIPPED", decision.task_id, decision.action, None,
            "deterministic_decision_does_not_allow_repair",
        )
    if category not in REPAIRABLE_CATEGORIES:
        return LocalAdvisorResult(
            "SKIPPED", decision.task_id, decision.action, None,
            "failure_category_not_allowlisted",
        )
    try:
        suggestion = advisor(decision.task_id, category, failing_tests)
    except (AdvisorError, OSError, ValueError, TypeError):
        return LocalAdvisorResult(
            "UNAVAILABLE", decision.task_id, decision.action, None,
            "local_advisor_unavailable_or_invalid",
        )

    # Do not expose a generic callable's arbitrary return value as trusted data.
    if (
        not isinstance(suggestion, dict)
        or set(suggestion) != {"diagnosis", "action", "risk"}
        or not all(isinstance(suggestion.get(key), str) and suggestion[key].strip()
                   for key in ("diagnosis", "action", "risk"))
    ):
        return LocalAdvisorResult(
            "UNAVAILABLE", decision.task_id, decision.action, None,
            "local_advisor_response_invalid",
        )
    return LocalAdvisorResult(
        "ADVISORY_ONLY", decision.task_id, decision.action,
        {key: suggestion[key].strip() for key in ("diagnosis", "action", "risk")},
        "suggestion_is_untrusted_and_requires_independent_review",
    )
