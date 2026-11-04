"""Structurally review Creator revision candidates against their approved briefs.

This Critic checks traceability, required deliverables, preservation declarations, and
safety boundaries. It does not judge artistic quality or modify production assets.
"""
from __future__ import annotations

from typing import Any


def review_creator_revision_candidates(
    revision_briefs: dict[str, Any],
    creator_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if (
        not isinstance(revision_briefs, dict)
        or revision_briefs.get("schema_version") != "audiovisual-creator-revision-briefs.v1"
    ):
        raise ValueError("revision_briefs must use audiovisual-creator-revision-briefs.v1")
    briefs = revision_briefs.get("briefs")
    policy = revision_briefs.get("execution_policy")
    if not isinstance(briefs, list) or not isinstance(policy, dict):
        raise ValueError("revision_briefs must contain briefs and execution_policy")
    if policy.get("automatic_revision_application") is not False:
        raise ValueError("revision briefs must prohibit automatic application")
    if policy.get("automatic_publication") is not False or policy.get("publication_authorized") is not False:
        raise ValueError("revision briefs must prohibit automatic publication")
    if not isinstance(creator_candidates, list):
        raise ValueError("creator_candidates must be a list")

    brief_by_id: dict[str, dict[str, Any]] = {}
    for brief in briefs:
        if not isinstance(brief, dict) or not isinstance(brief.get("brief_id"), str):
            raise ValueError("each revision brief must have a brief_id")
        brief_by_id[brief["brief_id"]] = brief

    findings: list[dict[str, Any]] = []
    reviewed: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    seen_brief_ids: set[str] = set()
    safety_hold = False

    def add_finding(severity: str, code: str, message: str, candidate_id: str | None = None) -> None:
        findings.append({
            "severity": severity,
            "code": code,
            "message": message,
            "candidate_id": candidate_id,
        })

    for candidate in creator_candidates:
        if not isinstance(candidate, dict):
            add_finding("blocker", "candidate_not_object", "Creator candidate must be a JSON object")
            safety_hold = True
            continue
        candidate_id = candidate.get("candidate_id")
        brief_id = candidate.get("brief_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            add_finding("blocker", "candidate_id_missing", "Candidate has no stable candidate_id")
            safety_hold = True
            continue
        if candidate_id in seen_candidate_ids:
            add_finding("blocker", "duplicate_candidate_id", "Candidate ID is duplicated", candidate_id)
            safety_hold = True
        seen_candidate_ids.add(candidate_id)
        if not isinstance(brief_id, str) or brief_id not in brief_by_id:
            add_finding("blocker", "unknown_brief_reference", "Candidate does not reference a known revision brief", candidate_id)
            safety_hold = True
            continue
        if brief_id in seen_brief_ids:
            add_finding("warning", "multiple_candidates_for_brief", "More than one candidate references this brief", candidate_id)
        seen_brief_ids.add(brief_id)
        brief = brief_by_id[brief_id]

        if candidate.get("asset_changes_requested") is True or candidate.get("publication_requested") is True:
            add_finding("blocker", "unsafe_execution_request", "Candidate requests asset changes or publication", candidate_id)
            safety_hold = True

        missing: list[str] = []
        for field in ("change_summary", "preserved_elements", "deliverables", "side_effects", "unknowns"):
            if field not in candidate:
                missing.append(field)
        for field in ("change_summary",):
            if not isinstance(candidate.get(field), str) or not candidate.get(field).strip():
                if field not in missing:
                    missing.append(field)
        for field in ("preserved_elements", "deliverables", "side_effects", "unknowns"):
            if not isinstance(candidate.get(field), list):
                if field not in missing:
                    missing.append(field)
        if missing:
            add_finding(
                "warning", "candidate_incomplete",
                "Missing or invalid candidate fields: " + ", ".join(missing),
                candidate_id,
            )

        preserved = candidate.get("preserved_elements")
        if isinstance(preserved, list):
            absent = [item for item in brief.get("preserve", []) if item not in preserved]
            if absent:
                add_finding(
                    "warning", "preservation_not_confirmed",
                    "Candidate does not explicitly confirm preservation of all brief constraints",
                    candidate_id,
                )
        deliverables = candidate.get("deliverables")
        if isinstance(deliverables, list):
            required = brief.get("deliverables", [])
            absent = [item for item in required if item not in deliverables]
            if absent:
                add_finding(
                    "warning", "required_deliverables_missing",
                    "Candidate omits one or more required comparison deliverables",
                    candidate_id,
                )

        reviewed.append({
            "candidate_id": candidate_id,
            "brief_id": brief_id,
            "source_proposal_id": brief.get("source_proposal_id"),
            "variant": brief.get("variant"),
            "structural_review_only": True,
            "artistic_quality_assessed": False,
            "human_listening_and_viewing_required": True,
            "human_approval_required_before_application": True,
        })

    missing_briefs = sorted(set(brief_by_id) - seen_brief_ids)
    if missing_briefs:
        add_finding(
            "warning", "briefs_without_candidates",
            "No Creator candidate supplied for: " + ", ".join(missing_briefs),
        )

    if safety_hold:
        status = "HOLD"
    elif findings:
        status = "REVIEW_REQUIRED"
    else:
        status = "STRUCTURAL_CHECKS_PASS"

    return {
        "schema_version": "audiovisual-revision-candidate-critic.v1",
        "status": status,
        "reviewed_candidate_count": len(reviewed),
        "findings": findings,
        "candidates": reviewed,
        "artistic_quality_assessed": False,
        "execution_policy": {
            "mode": "review_only",
            "automatic_revision_application": False,
            "automatic_asset_changes": False,
            "automatic_publication": False,
            "publication_authorized": False,
            "human_review_required": True,
        },
    }


__all__ = ["review_creator_revision_candidates"]
