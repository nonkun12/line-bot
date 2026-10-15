"""Explicit, advisory-only bridge from deterministic Recovery AI to local fm.

This bridge is opt-in and Mac-only. The decision must come from RecoveryStore;
the caller cannot supply or override the decision action. It never executes
suggestions, edits files, merges, or deploys.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from scripts.recovery_ai import (
    FAILURE_CATEGORIES, REPAIRABLE_CATEGORIES, RecoveryDecision, RecoveryStore,
)
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
    """Ask fm for investigation ideas only when the actual decision permits repair.

    This function does not persist state or alter the deterministic decision.
    Unsupported actions/categories and advisor failures return non-actionable status.
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


def record_failure_and_advise(
    store: RecoveryStore,
    task_id: str,
    category: str,
    failing_tests: Iterable[str] = (),
    *,
    transient_attempt: int = 1,
    advisor: Callable[..., dict[str, str]] = diagnose,
) -> tuple[RecoveryDecision, LocalAdvisorResult]:
    """Record one newly observed incident, then advise from the real decision.

    Call exactly once per newly observed incident: recording increments failure
    counters. State persistence errors propagate and prevent local AI invocation.
    """
    if category not in FAILURE_CATEGORIES:
        category = "unknown"
    tests = list(failing_tests)
    decision = store.record_failure(
        task_id, category, tests, transient_attempt=transient_attempt,
    )
    result = advise_for_decision(decision, category, tests, advisor=advisor)
    return decision, result


def main(argv: list[str] | None = None) -> int:
    """Record one fresh incident and optionally request a local diagnostic suggestion."""
    parser = argparse.ArgumentParser(
        description=(
            "Record one newly observed failure in RecoveryStore and request an "
            "advisory-only local fm suggestion if Recovery AI permits one."
        )
    )
    parser.add_argument("--state-file", required=True, help="Recovery state JSON path")
    parser.add_argument("--task-id", required=True, help="Sanitized task identifier")
    parser.add_argument(
        "--category", required=True, choices=sorted(FAILURE_CATEGORIES),
        help="Observed failure category",
    )
    parser.add_argument(
        "--failing-test", action="append", default=[], dest="failing_tests",
        help="Test identifier only; repeat for multiple tests. Never pass logs or secrets.",
    )
    parser.add_argument(
        "--transient-attempt", type=int, default=1,
        help="Current bounded transient attempt number (default: 1)",
    )
    args = parser.parse_args(argv)
    decision, result = record_failure_and_advise(
        RecoveryStore(Path(args.state_file)),
        args.task_id,
        args.category,
        args.failing_tests,
        transient_attempt=args.transient_attempt,
    )
    print(json.dumps({
        "decision": asdict(decision),
        "advisor": asdict(result),
        "note": "advisory only; no patch, command execution, merge, or deploy",
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result.status in {"ADVISORY_ONLY", "SKIPPED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
