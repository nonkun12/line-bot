"""Integrated structural and measured-signal review for audiovisual drafts.

The integrated pass combines the independent artifact critic with bounded WAV/MP4
measurements. It creates review prompts, not artistic judgments or automatic edits.
"""
from __future__ import annotations

from typing import Any

from agents.media.audiovisual_critic import review_audiovisual_draft
from agents.media.signal_analysis import attach_signal_evidence_to_critic


def review_audiovisual_production(
    scenario: dict[str, Any],
    music_plan: dict[str, Any],
    edl: dict[str, Any],
    storyboard: dict[str, Any],
    signal_report: dict[str, Any],
) -> dict[str, Any]:
    """Combine structural checks and measured signals into one read-only review."""
    report = review_audiovisual_draft(scenario, music_plan, edl, storyboard)
    report = attach_signal_evidence_to_critic(report, signal_report)

    comparison = signal_report.get("scene_comparison")
    if not isinstance(comparison, dict) or not isinstance(comparison.get("scenes"), list):
        raise ValueError("signal_report must contain scene comparison data")
    coverage = signal_report.get("video_coverage")
    if not isinstance(coverage, dict):
        raise ValueError("signal_report must contain video coverage data")

    cues = music_plan.get("cues", [])
    cue_by_id = {
        cue.get("scene_id"): cue for cue in cues
        if isinstance(cue, dict) and isinstance(cue.get("scene_id"), str)
    }
    measured_by_id = {
        scene.get("scene_id"): scene for scene in comparison["scenes"]
        if isinstance(scene, dict) and isinstance(scene.get("scene_id"), str)
    }

    aligned_scenes = []
    prompts = []
    for scene in scenario.get("scenes", []):
        if not isinstance(scene, dict) or not isinstance(scene.get("scene_id"), str):
            continue
        scene_id = scene["scene_id"]
        cue = cue_by_id.get(scene_id, {})
        measured = measured_by_id.get(scene_id, {})
        expected_energy = cue.get("energy")
        actual_rms = measured.get("audio_mean_rms_dbfs")
        actual_centroid = measured.get("audio_mean_spectral_centroid_hz")
        actual_luma = measured.get("video_mean_luma")
        actual_motion = measured.get("video_mean_frame_change_luma")
        aligned_scenes.append({
            "scene_id": scene_id,
            "intended_energy": expected_energy,
            "measured_audio_rms_dbfs": actual_rms,
            "measured_audio_spectral_centroid_hz": actual_centroid,
            "measured_video_luma": actual_luma,
            "measured_video_frame_change_luma": actual_motion,
            "audio_samples_available": bool(measured.get("audio_window_count", 0)),
            "video_samples_available": bool(measured.get("video_sample_count", 0)),
        })
        if actual_rms is None:
            prompts.append(f"{scene_id}: 音声サンプルがないため、音量と意図したエネルギーを聴感で確認する。")
        if actual_luma is None:
            prompts.append(f"{scene_id}: 映像サンプルがないため、画面の明暗と演出意図を目視確認する。")
        if expected_energy in {"low", "medium", "high"} and actual_rms is not None:
            prompts.append(
                f"{scene_id}: 意図した音楽エネルギーは{expected_energy}。"
                "RMSは参考値として扱い、編曲密度・旋律・聴感と合わせて確認する。"
            )

    findings = list(report.get("findings", []))
    if not coverage.get("scenario_coverage_complete", False):
        findings.append({
            "severity": "warning",
            "code": "measured_video_coverage_incomplete",
            "message": "映像信号のカバー範囲が不足しているため、未解析シーンを含む全体判断を保留する。",
        })
    if any(not item["audio_samples_available"] for item in aligned_scenes):
        findings.append({
            "severity": "warning",
            "code": "audio_signal_samples_missing",
            "message": "音声サンプルが不足しているシーンがあるため、聴感確認が必要。",
        })
    if any(not item["video_samples_available"] for item in aligned_scenes):
        findings.append({
            "severity": "warning",
            "code": "video_signal_samples_missing",
            "message": "映像サンプルが不足しているシーンがあるため、目視確認が必要。",
        })

    severity_rank = {"blocker": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda item: (
        severity_rank.get(item.get("severity"), 3),
        item.get("code", ""),
        item.get("message", ""),
    ))
    report.update({
        "schema_version": "integrated-audiovisual-review.v1",
        "status": (
            "HOLD" if any(item["severity"] == "blocker" for item in findings)
            else "REVIEW_REQUIRED" if any(item["severity"] == "warning" for item in findings)
            else "STRUCTURAL_CHECKS_PASS"
        ),
        "findings": findings,
        "warning_count": sum(item["severity"] == "warning" for item in findings),
        "signal_alignment": {
            "scenes": aligned_scenes,
            "review_prompts": prompts + [
                "RMS、スペクトル重心、明るさ、フレーム変化は測定値であり、感情や芸術性を直接表さない。",
                "意図と測定値の差は修正命令ではなく、Creatorと人間が確認する候補として扱う。",
            ],
            "video_coverage": dict(coverage),
            "automatic_quality_judgment": False,
            "automatic_asset_changes": False,
        },
        "review_limits": list(report.get("review_limits", [])) + [
            "Integrated signal alignment supplies evidence and listening/viewing prompts only; it does not infer artistic quality."
        ],
        "publication_authorized": False,
        "assets_modified": False,
    })
    return report


__all__ = ["review_audiovisual_production"]
