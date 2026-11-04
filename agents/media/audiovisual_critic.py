"""Independent, deterministic Creator-Critic checks for audiovisual draft bundles.

This is a structural critic, not a substitute for listening, watching, or human
creative judgment. It reports evidence-backed findings and never rewrites assets.
"""
from __future__ import annotations

from typing import Any


def review_audiovisual_draft(
    scenario: dict[str, Any],
    music_plan: dict[str, Any],
    edl: dict[str, Any],
    storyboard: dict[str, Any],
) -> dict[str, Any]:
    """Review cross-artifact consistency and production risks without mutation."""
    findings: list[dict[str, str]] = []

    def add(severity: str, code: str, message: str) -> None:
        findings.append({"severity": severity, "code": code, "message": message})

    if not isinstance(scenario, dict) or scenario.get("schema_version") != "video-scenario.v1":
        raise ValueError("scenario must use video-scenario.v1")
    if not isinstance(music_plan, dict) or music_plan.get("schema_version") != "video-music-plan.v1":
        raise ValueError("music_plan must use video-music-plan.v1")
    if not isinstance(edl, dict) or edl.get("schema_version") != "audiovisual-edl.v1":
        raise ValueError("edl must use audiovisual-edl.v1")
    if not isinstance(storyboard, dict) or storyboard.get("schema_version") != "video-storyboard.v1":
        raise ValueError("storyboard must use video-storyboard.v1")

    scenes = scenario.get("scenes")
    cues = music_plan.get("cues")
    video = edl.get("video_track")
    audio = edl.get("audio_track")
    panels = storyboard.get("panels")
    duration = scenario.get("creative_brief", {}).get("duration_seconds")
    if not all(isinstance(value, list) for value in (scenes, cues, video, audio, panels)):
        raise ValueError("scenario, music, EDL, and storyboard collections must be lists")
    if type(duration) is not int or duration <= 0:
        raise ValueError("scenario duration must be a positive integer")
    if any(item.get("duration_seconds") != duration for item in (music_plan, edl, storyboard)):
        add("blocker", "duration_mismatch", "Scenario, music plan, EDL, and storyboard durations must match.")

    scene_ids = [item.get("scene_id") for item in scenes if isinstance(item, dict)]
    cue_ids = [item.get("scene_id") for item in cues if isinstance(item, dict)]
    video_ids = [item.get("scene_id") for item in video if isinstance(item, dict)]
    audio_ids = [item.get("scene_id") for item in audio if isinstance(item, dict)]
    panel_ids = [item.get("scene_id") for item in panels if isinstance(item, dict)]
    expected = set(scene_ids)
    for name, ids in (
        ("music cues", cue_ids), ("video EDL", video_ids),
        ("audio EDL", audio_ids), ("storyboard", panel_ids),
    ):
        if len(ids) != len(set(ids)) or set(ids) != expected:
            add("blocker", "scene_coverage_mismatch", f"{name} must contain each scenario scene exactly once.")

    if len(scene_ids) != len(scenes) or len(scene_ids) != len(set(scene_ids)):
        add("blocker", "scenario_scene_ids_invalid", "Scenario scene IDs must be unique valid scene entries.")

    cue_by_id = {item["scene_id"]: item for item in cues if isinstance(item, dict) and isinstance(item.get("scene_id"), str)}
    video_by_id = {item["scene_id"]: item for item in video if isinstance(item, dict) and isinstance(item.get("scene_id"), str)}
    panel_by_id = {item["scene_id"]: item for item in panels if isinstance(item, dict) and isinstance(item.get("scene_id"), str)}
    for scene in scenes:
        if not isinstance(scene, dict) or not isinstance(scene.get("scene_id"), str):
            continue
        scene_id = scene["scene_id"]
        energy = scene.get("music_sync", {}).get("energy") if isinstance(scene.get("music_sync"), dict) else None
        cue = cue_by_id.get(scene_id)
        if cue is not None and cue.get("energy") != energy:
            add("warning", "emotional_energy_mismatch", f"{scene_id}: music cue energy differs from the scenario's emotional direction.")
        panel = panel_by_id.get(scene_id)
        if panel is not None:
            if panel.get("frame_description") != scene.get("visual_direction"):
                add("warning", "storyboard_visual_drift", f"{scene_id}: storyboard visual description differs from the scenario.")
            if panel.get("music_energy") != energy:
                add("warning", "storyboard_energy_drift", f"{scene_id}: storyboard music energy differs from the scenario.")
        video_scene = video_by_id.get(scene_id)
        if video_scene is not None and cue is not None:
            if video_scene.get("visual_sync_points") != cue.get("sync_points"):
                add("blocker", "sync_anchor_mismatch", f"{scene_id}: visual and audio sync anchors are not identical.")

        if isinstance(scene.get("dialogue_or_narration"), str) and scene["dialogue_or_narration"].strip():
            if cue is not None and cue.get("mix_priority") not in {"dialogue_first", "balanced"}:
                add("warning", "dialogue_mix_conflict", f"{scene_id}: dialogue/narration is present but music mix priority is not dialogue-first or balanced.")

        continuity = scene.get("continuity")
        if isinstance(continuity, dict) and continuity.get("must_match_previous_scene"):
            if not continuity.get("characters") and not continuity.get("props") and not continuity.get("location"):
                add("warning", "continuity_evidence_missing", f"{scene_id}: continuity is required but no character, prop, or location anchors are recorded.")

    beat_sync = edl.get("beat_sync")
    if not isinstance(beat_sync, dict) or not isinstance(beat_sync.get("events"), list):
        add("blocker", "beat_analysis_missing", "EDL must include a valid beat-sync event analysis.")
    else:
        events = beat_sync["events"]
        if len(events) != len(edl.get("sync_events", [])):
            add("blocker", "beat_event_count_mismatch", "Beat analysis and authored sync-event counts differ.")
        expressive = sum(
            1 for event in events
            if isinstance(event, dict) and event.get("alignment") == "expressive_offset"
        )
        if expressive:
            add("info", "expressive_timing_preserved", f"{expressive} authored off-beat events are retained as expressive timing, not errors.")

    if storyboard.get("render_status") != "rendered":
        add("info", "visual_assets_not_rendered", "Storyboard is a planning artifact; rendered visual assets still need review.")
    if edl.get("rights_status") != "cleared":
        add("warning", "rights_review_required", "Visual asset rights are not marked cleared; publication must remain blocked pending rights review.")

    severity_rank = {"blocker": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda item: (severity_rank[item["severity"]], item["code"], item["message"]))
    blockers = sum(item["severity"] == "blocker" for item in findings)
    warnings = sum(item["severity"] == "warning" for item in findings)
    deductions = min(100, blockers * 30 + warnings * 8)
    score = max(0, 100 - deductions)
    status = "HOLD" if blockers else ("REVIEW_REQUIRED" if warnings else "STRUCTURAL_CHECKS_PASS")
    return {
        "schema_version": "audiovisual-creator-critic.v1",
        "status": status,
        "structural_score": score,
        "score_is_subjective_quality": False,
        "blocker_count": blockers,
        "warning_count": warnings,
        "info_count": sum(item["severity"] == "info" for item in findings),
        "findings": findings,
        "review_limits": [
            "This deterministic pass checks artifact consistency, not artistic merit.",
            "It does not listen to the WAV or watch rendered video.",
            "A separate independent creative review must assess story clarity, emotional impact, pacing, and audiovisual harmony.",
            "Rights and factual claims require evidence before publication.",
        ],
        "publication_authorized": False,
        "assets_modified": False,
    }


__all__ = ["review_audiovisual_draft"]
