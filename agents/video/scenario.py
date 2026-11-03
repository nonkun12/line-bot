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
    if duration_seconds < scene_count:
        raise ValueError("duration_seconds must be at least scene_count to give every scene positive duration")

    scenes = []
    base, remainder = divmod(duration_seconds, scene_count)
    for index in range(scene_count):
        act_index = round(index * 3 / (scene_count - 1))
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
            "music_sync": {
                "emotional_intent": "このシーンで視聴者に届ける感情",
                "energy": {"opening": "low", "development": "medium", "climax": "high", "resolution": "low"}[act],
                "tempo_relation": "映像の動きと自然に呼吸を合わせる",
                "cue_in_seconds": 0,
                "cue_out_seconds": length,
                "sync_points": [
                    {"at_seconds": 0, "event": "シーン開始に合わせて音楽を導入"},
                    {"at_seconds": length, "event": "次シーンへの余韻または自然な接続"},
                ],
                "motif": "作品全体で一貫性を持たせる主題モチーフ",
                "mix_priority": "dialogue_first",
            },
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
        "audiovisual_direction": {
            "principle": "映像と音楽を同じ感情設計から作り、互いの表現を生かす",
            "emotional_arc": [
                {"act": "opening", "energy": "low", "music_role": "世界観を静かに提示"},
                {"act": "development", "energy": "medium", "music_role": "展開と期待を支える"},
                {"act": "climax", "energy": "high", "music_role": "映像の山場を強調し、過剰に競合しない"},
                {"act": "resolution", "energy": "low", "music_role": "余韻を残して自然に収束"},
            ],
            "global_music_motif": "全シーンを通して一貫する主題。必要に応じて編成・調性・リズムを変奏する",
            "mixing_rules": [
                "台詞がある区間では台詞の明瞭さを最優先し、BGMを自動的に控えめにする",
                "重要な映像イベントと音楽のアクセント位置を同期させる",
                "シーン間の音楽は唐突に切らず、クロスフェードまたは意図した無音で接続する",
                "効果音は音楽と周波数・タイミングが競合しないよう配置する",
                "無音も演出として使い、常時BGMを流すことを必須にしない",
            ],
        },
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
    if not isinstance(scenario.get("title"), str) or not scenario["title"].strip():
        errors.append("title_invalid")
    brief = scenario.get("creative_brief")
    scenes = scenario.get("scenes")
    if not isinstance(brief, dict) or not isinstance(scenes, list) or not scenes:
        return tuple(errors + ["creative_brief_or_scenes_missing"])

    duration = brief.get("duration_seconds")
    scene_count = brief.get("scene_count")
    if type(duration) is not int or not MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS:
        errors.append("duration_seconds_invalid")
    if type(scene_count) is not int or not MIN_SCENES <= scene_count <= MAX_SCENES:
        errors.append("scene_count_invalid")
    if len(scenes) != scene_count:
        errors.append("scene_count_mismatch")
    if type(duration) is int and len(scenes) > duration:
        errors.append("duration_shorter_than_scene_count")

    required_strings = (
        "purpose", "story_beat", "visual_direction", "action",
        "dialogue_or_narration", "audio_direction", "transition",
    )
    expected_start = 0
    seen_ids: set[str] = set()
    valid_energies = {"low", "medium", "high"}
    valid_mix = {"dialogue_first", "music_first", "balanced", "intentional_silence"}

    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            errors.append(f"scene_{index + 1}_invalid")
            continue
        scene_id = scene.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id.strip() or scene_id in seen_ids:
            errors.append("scene_ids_invalid_or_duplicate")
        else:
            seen_ids.add(scene_id)

        start = scene.get("time_start_seconds")
        scene_duration = scene.get("duration_seconds")
        if type(start) is not int or start != expected_start:
            errors.append(f"scene_{index + 1}_start_time_invalid")
        if type(scene_duration) is not int or scene_duration <= 0:
            errors.append(f"scene_{index + 1}_duration_invalid")
        elif type(start) is int:
            expected_start = start + scene_duration

        for key in required_strings:
            value = scene.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"scene_{index + 1}_{key}_invalid")
        if not isinstance(scene.get("continuity"), dict):
            errors.append(f"scene_{index + 1}_continuity_invalid")

        sync = scene.get("music_sync")
        if not isinstance(sync, dict):
            errors.append(f"scene_{index + 1}_music_sync_invalid")
            continue
        for key in ("emotional_intent", "tempo_relation", "motif"):
            value = sync.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"scene_{index + 1}_{key}_invalid")
        if sync.get("energy") not in valid_energies:
            errors.append(f"scene_{index + 1}_energy_invalid")

        cue_in = sync.get("cue_in_seconds")
        cue_out = sync.get("cue_out_seconds")
        if (
            type(cue_in) is not int or type(cue_out) is not int
            or type(scene_duration) is not int
            or cue_in < 0 or cue_out <= cue_in or cue_out > scene_duration
        ):
            errors.append(f"scene_{index + 1}_music_cue_timing_invalid")
        if sync.get("mix_priority") not in valid_mix:
            errors.append(f"scene_{index + 1}_mix_priority_invalid")
        points = sync.get("sync_points")
        if not isinstance(points, list) or any(
            not isinstance(point, dict)
            or type(point.get("at_seconds")) is not int
            or point["at_seconds"] < 0
            or (type(scene_duration) is int and point["at_seconds"] > scene_duration)
            or not isinstance(point.get("event"), str)
            or not point["event"].strip()
            for point in points
        ):
            errors.append(f"scene_{index + 1}_sync_points_invalid")

    if type(duration) is int and expected_start != duration:
        errors.append("scene_duration_total_mismatch")
    audiovisual = scenario.get("audiovisual_direction")
    if not isinstance(audiovisual, dict):
        errors.append("audiovisual_direction_missing")
    else:
        motif = audiovisual.get("global_music_motif")
        if not isinstance(motif, str) or not motif.strip():
            errors.append("global_music_motif_invalid")
        if not isinstance(audiovisual.get("mixing_rules"), list) or not audiovisual["mixing_rules"]:
            errors.append("mixing_rules_invalid")
        arc = audiovisual.get("emotional_arc")
        if not isinstance(arc, list) or not arc:
            errors.append("emotional_arc_invalid")
        elif any(
            not isinstance(item, dict)
            or item.get("act") not in {act[0] for act in _ACTS}
            or item.get("energy") not in valid_energies
            for item in arc
        ):
            errors.append("emotional_arc_invalid")
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
        {"id": "music_composition", "stage": "design", "depends_on": ["audio_plan"],
         "deliverable": "original music themes, motifs, arrangement, and scene-level cue timing"},
        {"id": "audiovisual_sync_review", "stage": "review",
         "depends_on": ["shot_list", "music_composition"],
         "deliverable": "verify emotional, rhythmic, transition, and mix harmony between picture and sound"},
        {"id": "production_readiness", "stage": "verify",
         "depends_on": ["audiovisual_sync_review", "audio_plan"],
         "deliverable": "validated production package"},
    ]


__all__ = ["build_scenario", "validate_scenario", "scenario_goal_jobs"]
