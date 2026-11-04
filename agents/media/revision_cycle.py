"""Plan a bounded Creator-Critic revision cycle without executing media changes.

The coordinator translates Critic findings into explicit Creator retry requests.
It never invokes a model, edits source assets, or authorizes production/publication.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


_RETRYABLE_CODES = {
    "candidate_incomplete",
    "preservation_not_confirmed",
    "required_deliverables_missing",
}
_MAX_ITERATIONS = 3


def plan_next_revision_iteration(
    revision_briefs: dict[str, Any],
    creator_candidates: list[dict[str, Any]],
    critic_report: dict[str, Any],
    *,
    iteration: int,
    max_iterations: int = 2,
) -> dict[str, Any]:
    """Return the next bounded Creator task batch or a terminal cycle decision."""
    if (
        not isinstance(revision_briefs, dict)
        or revision_briefs.get("schema_version") != "audiovisual-creator-revision-briefs.v1"
    ):
        raise ValueError("revision_briefs must use audiovisual-creator-revision-briefs.v1")
    policy = revision_briefs.get("execution_policy")
    briefs = revision_briefs.get("briefs")
    if not isinstance(policy, dict) or not isinstance(briefs, list):
        raise ValueError("revision_briefs must contain briefs and execution_policy")
    if (
        policy.get("automatic_revision_application") is not False
        or policy.get("automatic_publication") is not False
        or policy.get("publication_authorized") is not False
    ):
        raise ValueError("revision briefs must prohibit automatic application and publication")
    if not isinstance(creator_candidates, list):
        raise ValueError("creator_candidates must be a list")
    if not isinstance(critic_report, dict) or critic_report.get("schema_version") != "audiovisual-revision-candidate-critic.v1":
        raise ValueError("critic_report must use audiovisual-revision-candidate-critic.v1")
    if iteration < 1 or not isinstance(iteration, int):
        raise ValueError("iteration must be a positive integer")
    if not isinstance(max_iterations, int) or not 1 <= max_iterations <= _MAX_ITERATIONS:
        raise ValueError(f"max_iterations must be between 1 and {_MAX_ITERATIONS}")
    if iteration > max_iterations:
        raise ValueError("iteration cannot exceed max_iterations")

    brief_by_id = {
        brief["brief_id"]: brief
        for brief in briefs
        if isinstance(brief, dict) and isinstance(brief.get("brief_id"), str)
    }
    candidate_by_id: dict[str, dict[str, Any]] = {}
    for candidate in creator_candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("candidate_id"), str):
            raise ValueError("every Creator candidate must have a candidate_id")
        if candidate["candidate_id"] in candidate_by_id:
            raise ValueError("candidate_id values must be unique")
        candidate_by_id[candidate["candidate_id"]] = candidate

    status = critic_report.get("status")
    if status == "HOLD":
        decision = "STOP_HOLD"
        requests: list[dict[str, Any]] = []
    elif status == "STRUCTURAL_CHECKS_PASS":
        decision = "AWAIT_HUMAN_CREATIVE_REVIEW"
        requests = []
    elif status == "REVIEW_REQUIRED":
        if iteration >= max_iterations:
            decision = "ITERATION_LIMIT_REACHED"
            requests = []
        else:
            findings = critic_report.get("findings")
            if not isinstance(findings, list):
                raise ValueError("critic_report.findings must be a list")
            candidate_codes: dict[str, set[str]] = {}
            for finding in findings:
                if not isinstance(finding, dict):
                    raise ValueError("each critic finding must be an object")
                code = finding.get("code")
                candidate_id = finding.get("candidate_id")
                if code in _RETRYABLE_CODES and isinstance(candidate_id, str):
                    candidate_codes.setdefault(candidate_id, set()).add(code)
            requests = []
            for candidate_id in sorted(candidate_codes):
                candidate = candidate_by_id.get(candidate_id)
                if candidate is None:
                    raise ValueError("Critic finding references an unknown candidate")
                brief_id = candidate.get("brief_id")
                if brief_id not in brief_by_id:
                    raise ValueError("Creator candidate references an unknown brief")
                requests.append({
                    "request_id": f"ITER-{iteration + 1}-{candidate_id}",
                    "candidate_id": candidate_id,
                    "brief_id": brief_id,
                    "retry_reason_codes": sorted(candidate_codes[candidate_id]),
                    "instruction": (
                        "Revise only the identified omissions. Preserve story intent, "
                        "music/video sync anchors, rights metadata, and all unchanged elements. "
                        "Return a complete candidate; do not edit assets or publish."
                    ),
                    "required_creator_output": [
                        "change_summary", "preserved_elements", "deliverables",
                        "side_effects", "unknowns",
                    ],
                    "human_review_required": True,
                })
            decision = "REQUEST_CREATOR_REVISION" if requests else "STOP_NO_SAFE_RETRY"
    else:
        raise ValueError("critic_report.status is not a recognized terminal or review status")

    return {
        "schema_version": "audiovisual-revision-cycle-plan.v1",
        "iteration": iteration,
        "max_iterations": max_iterations,
        "decision": decision,
        "next_iteration": iteration + 1 if requests else None,
        "creator_requests": requests,
        "critic_status": status,
        "history_entry": {
            "iteration": iteration,
            "critic_status": status,
            "finding_count": len(critic_report.get("findings", []))
            if isinstance(critic_report.get("findings"), list) else 0,
            "candidate_count": len(creator_candidates),
            "decision": decision,
        },
        "execution_policy": {
            "mode": "planning_only",
            "model_invocation": False,
            "automatic_revision_application": False,
            "automatic_asset_changes": False,
            "automatic_publication": False,
            "publication_authorized": False,
            "human_approval_required_before_application": True,
        },
    }


__all__ = ["plan_next_revision_iteration"]
