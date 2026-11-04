"""Create bounded alternative-revision briefs from approved-shape feedback proposals.

This module creates planning artifacts only. It does not call a model, alter assets,
apply revisions, or authorize publication.
"""
from __future__ import annotations

from typing import Any


_VARIANTS = (
    {
        "variant": "conservative",
        "direction": "意図と既存構成を保ち、指摘された一点を最小限に改善する。",
        "change_scope": "single_focus",
    },
    {
        "variant": "exploratory",
        "direction": "同じシーン意図を保ちながら、表現方法を変えた別案を提示する。",
        "change_scope": "one_alternative_approach",
    },
)


def build_creator_revision_briefs(feedback: dict[str, Any]) -> dict[str, Any]:
    """Expand feedback proposals into two bounded, reviewable briefs each."""
    if not isinstance(feedback, dict) or feedback.get("schema_version") != "audiovisual-creator-feedback.v1":
        raise ValueError("feedback must use audiovisual-creator-feedback.v1")
    proposals = feedback.get("proposals")
    policy = feedback.get("execution_policy")
    if not isinstance(proposals, list) or not isinstance(policy, dict):
        raise ValueError("feedback must contain proposals and execution_policy")
    if policy.get("mode") != "proposal_only" or policy.get("automatic_asset_changes") is not False:
        raise ValueError("feedback execution policy is not safe for revision planning")
    if policy.get("automatic_publication") is not False or policy.get("publication_authorized") is not False:
        raise ValueError("feedback must explicitly prohibit automatic publication")

    briefs: list[dict[str, Any]] = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            raise ValueError("each proposal must be an object")
        if proposal.get("requires_human_approval_before_application") is not True:
            raise ValueError("each proposal must require human approval")
        proposal_id = proposal.get("proposal_id")
        source_code = proposal.get("source_finding_code")
        suggestion = proposal.get("suggestion")
        if not all(isinstance(value, str) and value for value in (proposal_id, source_code, suggestion)):
            raise ValueError("proposal_id, source_finding_code, and suggestion are required")
        for variant in _VARIANTS:
            briefs.append({
                "brief_id": f"{proposal_id}-{variant['variant'].upper()}",
                "source_proposal_id": proposal_id,
                "source_finding_code": source_code,
                "scene_id": proposal.get("scene_id"),
                "domain": proposal.get("domain"),
                "variant": variant["variant"],
                "creator_direction": variant["direction"],
                "evidence_context": proposal.get("evidence", {}),
                "requested_focus": suggestion,
                "preserve": [
                    "元シナリオの意図と物語上の連続性",
                    "既存の同期基準と明示された尺",
                    "素材の権利・出所情報",
                ],
                "deliverables": [
                    "変更点の説明",
                    "変更しない要素の説明",
                    "シーン単位の比較可能な代替案",
                    "想定される副作用と未確認事項",
                ],
                "scope": variant["change_scope"],
                "apply_revision": False,
                "requires_human_review": True,
                "requires_human_approval_before_application": True,
            })

    blockers_present = policy.get("blockers_present") is True
    return {
        "schema_version": "audiovisual-creator-revision-briefs.v1",
        "source_feedback_schema": feedback["schema_version"],
        "brief_count": len(briefs),
        "briefs": briefs,
        "execution_policy": {
            "mode": "planning_only",
            "production_blocked": blockers_present or policy.get("blockers_must_be_resolved_before_production") is True,
            "automatic_revision_application": False,
            "automatic_asset_changes": False,
            "automatic_publication": False,
            "publication_authorized": False,
            "human_review_required": True,
        },
    }


__all__ = ["build_creator_revision_briefs"]
