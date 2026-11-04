"""Compare Creator revision alternatives on structural evidence only.

The result is a comparison aid, not an artistic ranking or an automatic choice.
"""
from __future__ import annotations

from typing import Any


def compare_creator_revision_candidates(
    revision_briefs: dict[str, Any],
    creator_candidates: list[dict[str, Any]],
    critic_report: dict[str, Any],
) -> dict[str, Any]:
    if (
        not isinstance(revision_briefs, dict)
        or revision_briefs.get("schema_version") != "audiovisual-creator-revision-briefs.v1"
    ):
        raise ValueError("revision_briefs must use audiovisual-creator-revision-briefs.v1")
    briefs = revision_briefs.get("briefs")
    if not isinstance(briefs, list):
        raise ValueError("revision_briefs.briefs must be a list")
    if (
        not isinstance(critic_report, dict)
        or critic_report.get("schema_version") != "audiovisual-revision-candidate-critic.v1"
    ):
        raise ValueError("critic_report must use audiovisual-revision-candidate-critic.v1")
    findings = critic_report.get("findings")
    if not isinstance(findings, list):
        raise ValueError("critic_report.findings must be a list")
    if not isinstance(creator_candidates, list):
        raise ValueError("creator_candidates must be a list")

    brief_by_id: dict[str, dict[str, Any]] = {}
    for brief in briefs:
        if not isinstance(brief, dict) or not isinstance(brief.get("brief_id"), str):
            raise ValueError("each revision brief must have a brief_id")
        if brief["brief_id"] in brief_by_id:
            raise ValueError("revision brief IDs must be unique")
        brief_by_id[brief["brief_id"]] = brief

    candidate_by_id: dict[str, dict[str, Any]] = {}
    for candidate in creator_candidates:
        if not isinstance(candidate, dict):
            raise ValueError("each Creator candidate must be an object")
        candidate_id = candidate.get("candidate_id")
        brief_id = candidate.get("brief_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("each candidate must have a candidate_id")
        if candidate_id in candidate_by_id:
            raise ValueError("candidate IDs must be unique")
        if brief_id not in brief_by_id:
            raise ValueError("candidate references an unknown revision brief")
        if candidate.get("asset_changes_requested") is True or candidate.get("publication_requested") is True:
            raise ValueError("unsafe candidate requests cannot be compared")
        candidate_by_id[candidate_id] = candidate

    per_candidate: dict[str, dict[str, Any]] = {
        candidate_id: {
            "blocker_count": 0,
            "warning_count": 0,
            "info_count": 0,
            "finding_codes": {},
        }
        for candidate_id in candidate_by_id
    }
    global_findings: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("each Critic finding must be an object")
        severity = finding.get("severity")
        code = finding.get("code")
        candidate_id = finding.get("candidate_id")
        if severity not in {"blocker", "warning", "info"} or not isinstance(code, str) or not code:
            raise ValueError("Critic finding severity or code is invalid")
        if candidate_id is None:
            global_findings.append({"severity": severity, "code": code})
            continue
        if candidate_id not in per_candidate:
            raise ValueError("Critic finding references an unknown candidate")
        row = per_candidate[candidate_id]
        row[f"{severity}_count"] += 1
        row["finding_codes"][code] = row["finding_codes"].get(code, 0) + 1

    comparisons: list[dict[str, Any]] = []
    for candidate_id, candidate in candidate_by_id.items():
        brief = brief_by_id[candidate["brief_id"]]
        preserved = candidate.get("preserved_elements")
        deliverables = candidate.get("deliverables")
        missing_preservation = (
            [item for item in brief.get("preserve", []) if item not in preserved]
            if isinstance(preserved, list) else list(brief.get("preserve", []))
        )
        missing_deliverables = (
            [item for item in brief.get("deliverables", []) if item not in deliverables]
            if isinstance(deliverables, list) else list(brief.get("deliverables", []))
        )
        counts = per_candidate[candidate_id]
        comparisons.append({
            "candidate_id": candidate_id,
            "brief_id": candidate["brief_id"],
            "variant": brief.get("variant"),
            "domain": brief.get("domain"),
            "scene_id": brief.get("scene_id"),
            "critic_findings": {
                "blocker": counts["blocker_count"],
                "warning": counts["warning_count"],
                "info": counts["info_count"],
                "codes": dict(sorted(counts["finding_codes"].items())),
            },
            "missing_preservation_declarations": missing_preservation,
            "missing_required_deliverables": missing_deliverables,
            "structural_review_complete": (
                counts["blocker_count"] == 0
                and counts["warning_count"] == 0
                and not missing_preservation
                and not missing_deliverables
            ),
            "artistic_quality_assessed": False,
            "human_listening_and_viewing_required": True,
        })

    # Stable ordering is for inspection only; it is not a creative winner selection.
    comparisons.sort(key=lambda row: (
        row["critic_findings"]["blocker"],
        row["critic_findings"]["warning"],
        len(row["missing_preservation_declarations"]),
        len(row["missing_required_deliverables"]),
        row["candidate_id"],
    ))
    for index, row in enumerate(comparisons, start=1):
        row["structural_review_order"] = index

    return {
        "schema_version": "audiovisual-creator-candidate-comparison.v1",
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "global_critic_findings": global_findings,
        "selection": {
            "creative_winner_selected": False,
            "automatic_candidate_selection": False,
            "basis": "structural_findings_and_declared_deliverables_only",
            "human_creative_decision_required": True,
        },
        "execution_policy": {
            "comparison_only": True,
            "automatic_revision_application": False,
            "automatic_asset_changes": False,
            "automatic_publication": False,
            "publication_authorized": False,
        },
    }


__all__ = ["compare_creator_revision_candidates"]
