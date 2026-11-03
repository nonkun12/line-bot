"""Structured scenario design foundation for the Video specialist.

This module creates a validated, editable first-draft scenario contract. It is
provider-neutral: no paid API, external media service, or renderer is required.
Later creative models can enrich each scene without changing the downstream
storyboard, shot-list, audio, and Goal-JOB interfaces.
"""
from __future__ import annotations

from typing import Any

MIN_DURATION_SECONDS = 15
MAX_DURATION_SECONDS = 3600
MIN_SCENES = 2
MAX_SCENES = 20

_ACTS = (
    ("opening", "導入", "視聴者の関心をつかみ、状況と問いを提示する"),
    ("development", "展開", "目的・葛藤・発見を具体化して前へ進める"),
    ("climax", "山場", "最も重要な変化、発見、感情の頂点を描く"),
    ("resolution", "結び", "結果と余韻を示し、目的に沿って締めくくる"),
)


def _clean_text(value: object, field: str, *, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return value


def build_scenario(
    topic: str,
    *,
    title: str | None = None,
    genre: str = "未指定",
    audience: str = "一般視聴者",
    tone: str = "わかりやすく、印象に残る",
    premise: str | None = None,
    duration_seconds: int = 180,
    scene_count: int = 4,
) -> dict[str, Any]:
    """Build a bounded scene-by-scene scenario draft from a creative brief.

    The result is intentionally marked as a draft: it is a structured
    production brief, not a claim that dialogue or rendered footage is final.
    """
    subject = _clean_text(topic, "topic")
    if title is None:
        title = subject[:60]
    title = _clean_text(title, "title", limit=120)
    genre = _clean_text(genre, "genre", limit=80)
    audience = _clean_text(audience, "audience", limit=120)
    tone = _clean_text(tone, "tone", limit=120)
    premise = _clean_text(premise or subject, "premise", limit=1000)
    if type(duration_seconds) is not int or not MIN_DURATION_SECONDS <= duration_seconds <= MAX_DURATION_SECONDS:
        raise ValueError("duration_seconds must be an integer from 15 to 3600")
    if type(scene_count) is not int or not MIN_SCENES <= scene_count <= MAX_SCENES:
        raise ValueError("scene_count must be an integer from 2 to 20")

    scenes = []
    base, remainder = divmod(duration_seconds, scene_count)
    for index in range(scene_count):
        act_index = min(3, (index * 4) // scene_count)
        act, act_label, purpose = _ACTS[act_index]
        start = index * base + min(index, remainder)
        length = base + (1 if index < remainder else 0)
        scenes.append({
            "scene_id": f"SC{index + 1:02d}",
            "act": act,
            "act_label": act_label,
            "time_start_seconds": start,
            "duration_seconds": length,
            "purpose": purpose,
            "story_beat": (
                f"{subject}について、{purpose}。"
                if index == 0 else f"{premise}を軸に、{purpose}。"
            ),
            "visual_direction": "場所・被写体・構図・光・色調を具体化する",
            "action": "人物や対象の動きと、前後の状態変化を記述する",
            "dialogue_or_narration": "必要な台詞またはナレーションを作成する",
            "audio_direction": "環境音・効果音・音楽の役割と開始終了位置を指定する",
            "transition": "次のシーンへ自然につながる画面・音の変化を指定する",
            "continuity": {
                "characters": [],
                "props": [],
                "location": None,
                "wardrobe": [],
                "must_match_previous_scene": True if index else False,
            },
        })

    return {
        "schema_version": "video-scenario.v1",
        "status": "draft",
        "title": title,
        "creative_brief": {
            "topic": subject,
            "premise": premise,
            "genre": genre,
            "target_audience": audience,
            "tone": tone,
            "duration_seconds": duration_seconds,
            "scene_count": scene_count,
        },
        "story_structure": ["opening", "development", "climax", "resolution"],
        "scenes": scenes,
        "quality_gates": [
            "目的・対象視聴者・メッセージが一貫している",
            "全シーンの時間合計が指定尺と一致している",
            "登場人物・小道具・衣装・場所の連続性が保たれている",
            "映像・台詞・音響が各シーンの目的に貢献している",
            "権利・安全・事実関係に問題がない",
        ],
        "next_artifacts": ["screenplay", "storyboard", "shot_list", "audio_plan"],
        "human_review_required_for": ["公開・配信", "第三者の肖像・声・著作物の利用"],
    }


def validate_scenario(scenario: object) -> tuple[str, ...]:
    """Return contract violations; never silently repair a malformed draft."""
    if not isinstance(scenario, dict):
        return ("scenario_must_be_object",)
    errors: list[str] = []
    if scenario.get("schema_version") != "video-scenario.v1":
        errors.append("schema_version_invalid")
    if scenario.get("status") != "draft":
        errors.append("status_must_be_draft")
    brief = scenario.get("creative_brief")
    scenes = scenario.get("scenes")
    if not isinstance(brief, dict) or not isinstance(scenes, list) or not scenes:
        return tuple(errors + ["creative_brief_or_scenes_missing"])
    duration = brief.get("duration_seconds")
    if type(duration) is not int or sum(
        item.get("duration_seconds", 0) for item in scenes if isinstance(item, dict)
    ) != duration:
        errors.append("scene_duration_total_mismatch")
    ids = [item.get("scene_id") for item in scenes if isinstance(item, dict)]
    if len(ids) != len(scenes) or len(ids) != len(set(ids)):
        errors.append("scene_ids_invalid_or_duplicate")
    required = ("purpose", "story_beat", "visual_direction", "action",
                "dialogue_or_narration", "audio_direction", "transition", "continuity")
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict) or any(not scene.get(key) for key in required):
            errors.append(f"scene_{index + 1}_incomplete")
    return tuple(errors)


def scenario_goal_jobs(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a dependency-ordered production plan for Goal AI registration."""
    errors = validate_scenario(scenario)
    if errors:
        raise ValueError("invalid scenario: " + ", ".join(errors))
    return [
        {"id": "screenplay", "stage": "design", "depends_on": [],
         "deliverable": "scene dialogue and narration"},
        {"id": "continuity_review", "stage": "review", "depends_on": ["screenplay"],
         "deliverable": "character, prop, wardrobe, location continuity report"},
        {"id": "storyboard", "stage": "design", "depends_on": ["continuity_review"],
         "deliverable": "visual storyboard for every scene"},
        {"id": "shot_list", "stage": "design", "depends_on": ["storyboard"],
         "deliverable": "camera, framing, movement, and timing plan"},
        {"id": "audio_plan", "stage": "design", "depends_on": ["screenplay"],
         "deliverable": "dialogue, ambience, effects, and original music cues"},
        {"id": "production_readiness", "stage": "verify",
         "depends_on": ["shot_list", "audio_plan"],
         "deliverable": "validated production package"},
    ]


__all__ = ["build_scenario", "validate_scenario", "scenario_goal_jobs"]
