"""Readable screenplay draft generation from the validated audiovisual scenario."""
from __future__ import annotations

from typing import Any

from agents.video.scenario import validate_scenario


def _timestamp(seconds: int) -> str:
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes:02d}:{remainder:02d}"


def render_screenplay_markdown(scenario: dict[str, Any]) -> str:
    """Render the scenario as an editable Japanese screenplay/production draft."""
    errors = validate_scenario(scenario)
    if errors:
        raise ValueError("invalid scenario: " + ", ".join(errors))

    brief = scenario["creative_brief"]
    lines = [
        f"# {scenario['title']}",
        "",
        "> 脚本・演出初稿。人物・場所・固有の出来事は未確定。制作・公開前に内容と権利を確認する。",
        "",
        f"- ジャンル: {brief['genre']}",
        f"- 対象: {brief['target_audience']}",
        f"- トーン: {brief['tone']}",
        f"- 尺: {brief['duration_seconds']}秒",
        f"- 主題: {brief['topic']}",
        "",
        "## 作品の軸",
        "",
        str(brief["premise"]),
        "",
        "## 映像と音楽の共通設計",
        "",
        str(scenario["audiovisual_direction"]["principle"]),
        "",
        f"**全編モチーフ:** {scenario['audiovisual_direction']['global_music_motif']}",
        "",
    ]

    for index, scene in enumerate(scenario["scenes"], start=1):
        start = scene["time_start_seconds"]
        end = start + scene["duration_seconds"]
        shot = scene["shot_plan"]
        sync = scene["music_sync"]
        continuity = scene["continuity"]
        lines.extend([
            f"## Scene {index:02d} — {scene['act_label']}",
            "",
            f"**時間:** {_timestamp(start)}–{_timestamp(end)}（{scene['duration_seconds']}秒）",
            "",
            f"**シーンの目的:** {scene['purpose']}",
            "",
            f"**映像:** {scene['visual_direction']}",
            "",
            f"**動作:** {scene['action']}",
            "",
            f"**台詞・ナレーション:** {scene['dialogue_or_narration']}",
            "",
            f"**ショット:** {shot['shot_size']} / {shot['camera_motion']} / 主題: {shot['focal_subject']}",
            "",
            f"**照明・色:** {shot['lighting']} / {shot['color_palette']}",
            "",
            f"**構図:** {shot['composition_note']}",
            "",
            f"**音響:** {scene['audio_direction']}",
            "",
            f"**音楽:** 感情={sync['emotional_intent']}、強度={sync['energy']}、モチーフ={sync['motif']}、ミックス={sync['mix_priority']}",
            "",
            "**音楽同期点:**",
        ])
        for point in sync["sync_points"]:
            lines.append(f"- +{point['at_seconds']}秒: {point['event']}")
        lines.extend([
            "",
            f"**場面転換:** {scene['transition']}",
            "",
            f"**連続性メモ:** 人物={continuity.get('characters', [])} / 小道具={continuity.get('props', [])} / 場所={continuity.get('location')}",
            "",
        ])

    lines.extend([
        "## 制作前レビュー",
        "",
        *[f"- {item}" for item in scenario["quality_gates"]],
        "",
        "## 創作上の仮定",
        "",
        *[f"- {item}" for item in scenario["creative_assumptions"]],
        "",
        "## 権利・公開",
        "",
        "第三者の肖像・声・著作物、実在の場所や事実を使う場合は、利用許諾と事実確認を完了するまで公開しない。",
        "",
    ])
    return "\n".join(lines)


__all__ = ["render_screenplay_markdown"]
