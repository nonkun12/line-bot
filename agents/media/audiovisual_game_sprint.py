"""Create a bounded end-to-end audiovisual-to-game sprint dependency plan.

This module describes the production pipeline. It does not execute jobs, call
models, modify assets, or authorize publication, merge, or deployment.
"""
from __future__ import annotations

import re
from typing import Any


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_MAX_REVISION_ITERATIONS = 3


def build_audiovisual_game_sprint_plan(
    goal_id: str,
    objective: str,
    *,
    max_revision_iterations: int = 2,
    target_platform: str = "desktop",
) -> dict[str, Any]:
    if not isinstance(goal_id, str) or not _ID.fullmatch(goal_id):
        raise ValueError("goal_id must be a stable identifier")
    if not isinstance(objective, str) or not objective.strip() or len(objective) > 1000:
        raise ValueError("objective must contain 1..1000 characters")
    if (
        type(max_revision_iterations) is not int
        or not 1 <= max_revision_iterations <= _MAX_REVISION_ITERATIONS
    ):
        raise ValueError(f"max_revision_iterations must be between 1 and {_MAX_REVISION_ITERATIONS}")
    if target_platform not in {"desktop", "web"}:
        raise ValueError("target_platform must be desktop or web")

    stages = [
        {
            "job_id": "scenario",
            "stage": "story",
            "depends_on": [],
            "input_artifacts": ["creative_goal"],
            "output_artifacts": ["video-scenario.v1", "screenplay.v1"],
            "acceptance": ["story intent is explicit", "scene timing and continuity are traceable"],
            "human_gate": "scenario_direction_review",
        },
        {
            "job_id": "music",
            "stage": "composition",
            "depends_on": ["scenario"],
            "input_artifacts": ["video-scenario.v1"],
            "output_artifacts": ["music-plan.v1", "MIDI", "WAV"],
            "acceptance": ["motifs and scene energy are mapped", "music timing preserves expressive intent"],
            "human_gate": "listening_review",
        },
        {
            "job_id": "visual",
            "stage": "visual_design",
            "depends_on": ["scenario"],
            "input_artifacts": ["video-scenario.v1"],
            "output_artifacts": ["storyboard.v1", "shot-list.v1", "EDL"],
            "acceptance": ["each scene has visual intent", "visual sync points are traceable"],
            "human_gate": "storyboard_review",
        },
        {
            "job_id": "sync",
            "stage": "audiovisual_sync",
            "depends_on": ["music", "visual"],
            "input_artifacts": ["music-plan.v1", "EDL"],
            "output_artifacts": ["audiovisual-sync-timeline.v1", "audiovisual-sync-edit-plan.v1"],
            "acceptance": ["on-beat and expressive offsets are identified", "authored timing is unchanged"],
            "human_gate": None,
        },
        {
            "job_id": "render",
            "stage": "local_media_creation",
            "depends_on": ["scenario", "music", "visual", "sync"],
            "input_artifacts": ["video-scenario.v1", "MIDI", "WAV", "storyboard.v1", "EDL"],
            "output_artifacts": ["local-media-receipt.v1", "preview-video"],
            "acceptance": ["local render is bounded and reproducible", "outputs have integrity receipts"],
            "human_gate": "render_preview_review",
        },
        {
            "job_id": "signal",
            "stage": "signal_analysis",
            "depends_on": ["render"],
            "input_artifacts": ["WAV", "preview-video", "video-scenario.v1"],
            "output_artifacts": ["audiovisual-signal-analysis.v1"],
            "acceptance": ["audio and video coverage is reported", "measurements are descriptive only"],
            "human_gate": None,
        },
        {
            "job_id": "critic",
            "stage": "creator_critic_review",
            "depends_on": ["signal", "sync"],
            "input_artifacts": ["video-scenario.v1", "music-plan.v1", "storyboard.v1", "EDL", "audiovisual-signal-analysis.v1"],
            "output_artifacts": ["integrated-audiovisual-review.v1", "audiovisual-creator-feedback.v1"],
            "acceptance": ["structural and measured evidence are linked", "blockers force HOLD"],
            "human_gate": "listening_and_viewing_review",
        },
        {
            "job_id": "revision",
            "stage": "bounded_creator_critic_loop",
            "depends_on": ["critic"],
            "input_artifacts": ["audiovisual-creator-feedback.v1"],
            "output_artifacts": ["audiovisual-creator-revision-briefs.v1", "audiovisual-revision-candidate-critic.v1", "audiovisual-revision-history.v1", "audiovisual-creator-candidate-comparison.v1"],
            "acceptance": [
                f"revision iterations do not exceed {max_revision_iterations}",
                "structural improvement is measured without inferring artistic quality",
                "HOLD stops the cycle",
            ],
            "human_gate": "creative_candidate_decision",
            "max_iterations": max_revision_iterations,
        },
        {
            "job_id": "decision",
            "stage": "human_creative_decision",
            "depends_on": ["revision"],
            "input_artifacts": ["audiovisual-creator-candidate-comparison.v1"],
            "output_artifacts": ["audiovisual-human-creative-decision.v1"],
            "acceptance": ["human confirms listening and viewing", "selected candidate passes structural completeness"],
            "human_gate": "explicit_human_decision",
        },
        {
            "job_id": "godot_design",
            "stage": "interactive_game_design",
            "depends_on": ["decision"],
            "input_artifacts": ["video-scenario.v1", "audiovisual-human-creative-decision.v1"],
            "output_artifacts": ["godot-game-design.v1", "interaction-spec.v1"],
            "acceptance": ["core interaction derives from the story", "music and visual motifs inform game feedback"],
            "human_gate": "gameplay_concept_review",
        },
        {
            "job_id": "godot_prototype",
            "stage": "game_prototype",
            "depends_on": ["godot_design"],
            "input_artifacts": ["godot-game-design.v1", "interaction-spec.v1", "approved audiovisual assets"],
            "output_artifacts": ["Godot prototype project", "playtest build"],
            "acceptance": ["prototype runs on the selected platform", "core loop is playable", "audio and visuals remain synchronized"],
            "human_gate": "prototype_playtest",
            "target_platform": target_platform,
        },
        {
            "job_id": "game_test",
            "stage": "game_validation",
            "depends_on": ["godot_prototype"],
            "input_artifacts": ["playtest build"],
            "output_artifacts": ["game-test-report.v1", "next-sprint-backlog.v1"],
            "acceptance": ["automated checks pass", "playtest findings are recorded", "next sprint is prioritized"],
            "human_gate": "sprint_review",
        },
    ]

    job_ids = {item["job_id"] for item in stages}
    for item in stages:
        if any(dep not in job_ids for dep in item["depends_on"]):
            raise ValueError("sprint plan contains an unknown dependency")

    return {
        "schema_version": "audiovisual-to-game-sprint-plan.v1",
        "goal_id": goal_id,
        "objective": objective.strip(),
        "target_platform": target_platform,
        "development_method": "iterative_sprints",
        "stages": stages,
        "dependency_order": [item["job_id"] for item in stages],
        "free_toolchain": {
            "scenario_and_planning": "repository-native Python modules",
            "music": "MIDI generation and free soundfonts or original recordings",
            "video": "Blender and FFmpeg",
            "editing": "DaVinci Resolve free edition (optional local editing)",
            "game_engine": "Godot",
        },
        "safety_policy": {
            "bounded_revision_iterations": max_revision_iterations,
            "blocker_stops_pipeline": True,
            "human_gates_are_mandatory": True,
            "automatic_asset_changes_without_approval": False,
            "automatic_publication": False,
            "automatic_merge": False,
            "automatic_deployment": False,
            "paid_services_required": False,
        },
        "execution_state": "PLAN_ONLY",
    }


__all__ = ["build_audiovisual_game_sprint_plan"]
