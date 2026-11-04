"""Append-only, structural history for bounded audiovisual revision cycles.

The history records Critic outcomes for comparison. It does not infer artistic
quality, select a creative winner, or authorize edits/publication.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


_HISTORY_SCHEMA = "audiovisual-revision-history.v1"
_CRITIC_SCHEMA = "audiovisual-revision-candidate-critic.v1"
_PLAN_SCHEMA = "audiovisual-revision-cycle-plan.v1"
_VALID_STATUSES = {"HOLD", "REVIEW_REQUIRED", "STRUCTURAL_CHECKS_PASS"}


def _finding_counts(report: dict[str, Any]) -> dict[str, int]:
    findings = report.get("findings")
    if not isinstance(findings, list):
        raise ValueError("critic_report.findings must be a list")
    counts: dict[str, int] = {}
    for finding in findings:
        if not isinstance(finding, dict) or not isinstance(finding.get("code"), str):
            raise ValueError("each Critic finding must contain a string code")
        code = finding["code"]
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def append_revision_history(
    history: dict[str, Any] | None,
    cycle_plan: dict[str, Any],
    critic_report: dict[str, Any],
) -> dict[str, Any]:
    """Return a new history artifact with exactly one sequential entry appended."""
    if history is None:
        history = {"schema_version": _HISTORY_SCHEMA, "entries": []}
    if (
        not isinstance(history, dict)
        or history.get("schema_version") != _HISTORY_SCHEMA
        or not isinstance(history.get("entries"), list)
    ):
        raise ValueError("history must use audiovisual-revision-history.v1")
    if not isinstance(cycle_plan, dict) or cycle_plan.get("schema_version") != _PLAN_SCHEMA:
        raise ValueError("cycle_plan must use audiovisual-revision-cycle-plan.v1")
    if not isinstance(critic_report, dict) or critic_report.get("schema_version") != _CRITIC_SCHEMA:
        raise ValueError("critic_report must use audiovisual-revision-candidate-critic.v1")

    iteration = cycle_plan.get("iteration")
    if not isinstance(iteration, int) or iteration < 1:
        raise ValueError("cycle_plan.iteration must be a positive integer")
    entries = history["entries"]
    expected = len(entries) + 1
    if iteration != expected:
        raise ValueError(f"history requires sequential iteration {expected}")
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or entry.get("iteration") != index:
            raise ValueError("existing history entries must be sequential and valid")

    status = critic_report.get("status")
    if status not in _VALID_STATUSES:
        raise ValueError("critic_report.status is not recognized")
    if cycle_plan.get("critic_status") != status:
        raise ValueError("cycle plan and Critic report statuses do not match")

    counts = _finding_counts(critic_report)
    previous_total = sum(entries[-1]["finding_counts"].values()) if entries else None
    current_total = sum(counts.values())
    if previous_total is None:
        comparison = "BASELINE"
    elif current_total < previous_total:
        comparison = "FEWER_STRUCTURAL_FINDINGS"
    elif current_total > previous_total:
        comparison = "MORE_STRUCTURAL_FINDINGS"
    else:
        comparison = "SAME_STRUCTURAL_FINDING_COUNT"

    new_entry = {
        "iteration": iteration,
        "critic_status": status,
        "cycle_decision": cycle_plan.get("decision"),
        "finding_counts": counts,
        "total_structural_findings": current_total,
        "comparison_to_previous": comparison,
        "candidate_count": critic_report.get("reviewed_candidate_count", 0),
        "artistic_quality_assessed": False,
        "human_listening_and_viewing_required": True,
    }
    result = deepcopy(history)
    result["entries"].append(new_entry)
    result["latest_iteration"] = iteration
    result["latest_critic_status"] = status
    result["execution_policy"] = {
        "append_only_result": True,
        "artistic_quality_assessed": False,
        "automatic_revision_application": False,
        "automatic_asset_changes": False,
        "automatic_publication": False,
        "publication_authorized": False,
        "human_review_required": True,
    }
    return result


__all__ = ["append_revision_history"]
