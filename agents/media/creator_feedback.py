"""Turn audiovisual review evidence into bounded, human-approved Creator suggestions.

Suggestions are proposals only: this module never edits media or source artifacts,
does not infer artistic quality from signal measurements, and never authorizes publication.
"""
from __future__ import annotations

from typing import Any


_FINDING_GUIDANCE = {
    "emotional_energy_mismatch": (
        "music", "energy_and_arrangement",
        "シーンの意図したエネルギーと音楽キューをCreatorが再確認し、必要なら編曲密度・音域・強弱の別案を作る。",
    ),
    "storyboard_visual_drift": (
        "visual", "storyboard_alignment",
        "シナリオの画面意図とストーリーボードを照合し、構図・ショット・色調の整合案を作る。",
    ),
    "storyboard_energy_drift": (
        "visual_music", "cross_modal_alignment",
        "絵コンテの音楽エネルギー指定をシナリオと照合し、映像変化と音楽の呼吸を合わせる別案を作る。",
    ),
    "dialogue_mix_conflict": (
        "music", "dialogue_mix",
        "台詞・ナレーションの明瞭さを優先する編成、帯域、音量オートメーションの案を作る。",
    ),
    "continuity_evidence_missing": (
        "story", "continuity",
        "人物・小道具・場所など、前シーンから引き継ぐ要素をシナリオ担当に確認し、連続性メモの案を作る。",
    ),
    "rights_review_required": (
        "production", "rights",
        "素材の権利根拠を確認する。権利が確認できるまで素材利用・公開に進まない。",
    ),
    "measured_video_coverage_incomplete": (
        "review", "video_coverage",
        "未解析または一部解析のシーンを追加サンプリングしてから映像レビューを行う。",
    ),
    "audio_signal_samples_missing": (
        "review", "audio_coverage",
        "音声サンプルがないシーンの音声ファイルと区間指定を確認し、再解析する。",
    ),
    "video_signal_samples_missing": (
        "review", "video_coverage",
        "映像サンプルがないシーンの映像ファイルと区間指定を確認し、再解析する。",
    ),
}

_SIGNAL_PROMPT = (
    "測定値を修正命令にせず、実際に聴く・見る。明暗、音量、スペクトル、動きが"
    "演出意図に合うかを人間が判断し、必要ならCreatorが複数案を提示する。"
)


def build_creator_feedback_candidates(review_report: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic evidence-linked suggestions from an integrated review."""
    if not isinstance(review_report, dict) or review_report.get("schema_version") != "integrated-audiovisual-review.v1":
        raise ValueError("review_report must use integrated-audiovisual-review.v1")
    findings = review_report.get("findings")
    alignment = review_report.get("signal_alignment")
    if not isinstance(findings, list) or not isinstance(alignment, dict):
        raise ValueError("review_report must contain findings and signal_alignment")
    scenes = alignment.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("signal_alignment.scenes must be a list")

    proposals: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        code = finding.get("code")
        if not isinstance(code, str) or code not in _FINDING_GUIDANCE:
            continue
        domain, action, suggestion = _FINDING_GUIDANCE[code]
        message = finding.get("message", "")
        scene_id = None
        if isinstance(message, str):
            for scene in scenes:
                candidate_id = scene.get("scene_id") if isinstance(scene, dict) else None
                if isinstance(candidate_id, str) and candidate_id in message:
                    scene_id = candidate_id
                    break
        key = (code, scene_id or "", action)
        if key in seen:
            continue
        seen.add(key)
        proposals.append({
            "proposal_id": f"FB-{len(proposals) + 1:03d}",
            "source_finding_code": code,
            "severity": finding.get("severity", "info"),
            "scene_id": scene_id,
            "domain": domain,
            "action": action,
            "suggestion": suggestion,
            "evidence": {
                "finding_message": message if isinstance(message, str) else "",
                "measured_signal_is_not_aesthetic_judgment": True,
            },
            "requires_creator_review": True,
            "requires_human_approval_before_application": True,
        })

    scene_prompts = []
    for scene in scenes:
        if not isinstance(scene, dict) or not isinstance(scene.get("scene_id"), str):
            continue
        scene_prompts.append({
            "scene_id": scene["scene_id"],
            "prompt": _SIGNAL_PROMPT,
            "measurements": {
                key: scene.get(key) for key in (
                    "intended_energy", "measured_audio_rms_dbfs",
                    "measured_audio_spectral_centroid_hz", "measured_video_luma",
                    "measured_video_frame_change_luma", "audio_samples_available",
                    "video_samples_available",
                )
            },
            "measurements_are_descriptive_only": True,
        })

    blockers = [
        item for item in findings
        if isinstance(item, dict) and item.get("severity") == "blocker"
    ]
    return {
        "schema_version": "audiovisual-creator-feedback.v1",
        "source_review_schema": review_report["schema_version"],
        "source_review_status": review_report.get("status"),
        "proposal_count": len(proposals),
        "proposals": proposals,
        "scene_review_prompts": scene_prompts,
        "execution_policy": {
            "mode": "proposal_only",
            "creator_may_generate_alternatives": True,
            "automatic_source_edits": False,
            "automatic_asset_changes": False,
            "automatic_publication": False,
            "publication_authorized": False,
            "human_approval_required": True,
            "blockers_present": bool(blockers),
            "blockers_must_be_resolved_before_production": bool(blockers),
        },
    }


__all__ = ["build_creator_feedback_candidates"]
