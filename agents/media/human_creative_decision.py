"""Record an explicit human creative decision from a structural comparison."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def record_human_creative_decision(
    comparison_report: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    if (
        not isinstance(comparison_report, dict)
        or comparison_report.get("schema_version") != "audiovisual-creator-candidate-comparison.v1"
    ):
        raise ValueError("comparison_report must use audiovisual-creator-candidate-comparison.v1")
    comparisons = comparison_report.get("comparisons")
    if not isinstance(comparisons, list):
        raise ValueError("comparison_report.comparisons must be a list")
    if not isinstance(decision, dict):
        raise ValueError("decision must be an object")

    action = decision.get("action")
    if action not in {"select_candidate", "request_revision", "reject_all"}:
        raise ValueError("unsupported human decision action")
    rationale = decision.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 2000:
        raise ValueError("a non-empty rationale of at most 2000 characters is required")
    if decision.get("human_confirmed_listening") is not True:
        raise ValueError("human listening confirmation is required")
    if decision.get("human_confirmed_viewing") is not True:
        raise ValueError("human viewing confirmation is required")

    by_id: dict[str, dict[str, Any]] = {}
    for item in comparisons:
        if not isinstance(item, dict) or not isinstance(item.get("candidate_id"), str):
            raise ValueError("comparison entries must contain candidate_id")
        if item["candidate_id"] in by_id:
            raise ValueError("comparison candidate IDs must be unique")
        by_id[item["candidate_id"]] = item

    candidate_id = decision.get("candidate_id")
    global_findings = comparison_report.get("global_critic_findings", [])
    if not isinstance(global_findings, list):
        raise ValueError("global_critic_findings must be a list")
    unresolved_global = [
        item for item in global_findings
        if isinstance(item, dict) and item.get("severity") in {"blocker", "warning"}
    ]
    if action == "select_candidate" and unresolved_global:
        raise ValueError("global Critic findings must be resolved before candidate selection")
    if action == "select_candidate":
        if not isinstance(candidate_id, str) or candidate_id not in by_id:
            raise ValueError("selected candidate must exist in comparison report")
        if by_id[candidate_id].get("structural_review_complete") is not True:
            raise ValueError("candidate must pass structural completeness before selection")
    elif action == "request_revision":
        if not isinstance(candidate_id, str) or candidate_id not in by_id:
            raise ValueError("revision target must exist in comparison report")
    elif candidate_id is not None:
        raise ValueError("reject_all must not specify a candidate_id")

    result = {
        "schema_version": "audiovisual-human-creative-decision.v1",
        "action": action,
        "candidate_id": candidate_id,
        "rationale": rationale.strip(),
        "human_confirmed_listening": True,
        "human_confirmed_viewing": True,
        "source_comparison_schema": comparison_report["schema_version"],
        "structural_review_order_is_not_artistic_ranking": True,
        "decision_recorded": True,
        "execution_policy": {
            "decision_record_only": True,
            "automatic_revision_application": False,
            "automatic_asset_changes": False,
            "automatic_publication": False,
            "publication_authorized": False,
            "human_approval_required_before_application": True,
        },
    }
    return deepcopy(result)


__all__ = ["record_human_creative_decision"]
