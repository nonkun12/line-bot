"""Safe composition of deterministic Recovery AI and the Mac-local advisor.

The deterministic controller always makes the recovery decision first. Apple
Foundation Models can add diagnostic text only; advisor failures are ignored and
never alter the decision, retry budget, task hold, patch, resume, or deployment.
This module is intended for an explicitly enabled local macOS caller, not hosted
GitHub Actions (which do not have access to the Mac's `fm` CLI).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from scripts.apple_foundation_models_advisor import AdvisorResult, advise
from scripts.recovery_ai import RecoveryDecision, RecoveryStore


@dataclass(frozen=True)
class RecoveryAssessment:
    decision: RecoveryDecision
    advisor: AdvisorResult


def record_failure_with_local_advice(
    store: RecoveryStore,
    task_id: str,
    category: str,
    failing_tests: Iterable[str] = (),
    *,
    transient_attempt: int = 1,
    advisor_enabled: bool = False,
) -> RecoveryAssessment:
    """Record failure deterministically; optionally attach read-only Mac advice.

    Opt-in is explicit. If the deterministic state write fails, this function
    raises before contacting the model. Advisor exceptions fail closed to no
    advice and cannot change the already-computed RecoveryDecision.
    """
    tests = tuple(failing_tests)
    decision = store.record_failure(
        task_id, category, tests, transient_attempt=transient_attempt
    )
    # Verify the persisted state before any optional model call. A successful
    # write return alone is not enough evidence that the state can be read back.
    persisted = store.task_status(task_id)
    if (
        not isinstance(persisted, dict)
        or persisted.get("last_category") != category
        or persisted.get("last_fingerprint") != decision.fingerprint
        or persisted.get("consecutive_failures") != decision.consecutive_failures
    ):
        from scripts.recovery_ai import RecoveryStateError
        raise RecoveryStateError("recovery state read-back verification failed")
    if not advisor_enabled or category == "state_persistence_failure":
        return RecoveryAssessment(
            decision, AdvisorResult(False, reason="advisor_disabled_or_not_applicable")
        )
    try:
        advisory = advise(task_id, category, tests)
    except Exception:
        # The advisor is optional diagnostics only. Its failure must not affect
        # the deterministic recovery decision or interrupt the caller.
        advisory = AdvisorResult(False, reason="advisor_unexpected_error")
    return RecoveryAssessment(decision, advisory)
