"""Build a cloud-native, free-tool draft bundle for STAR-NIGHT episode 001.

This job creates editable story/visual plans and original MIDI/WAV assets using
Python-only renderers. It does not call paid APIs, download media, publish, or
pretend that a storyboard is final video footage.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agents.media.audiovisual_critic import review_audiovisual_draft
from agents.media.production import create_audiovisual_production_bundle
from agents.video.scenario import build_scenario


_SCENES = (
    {
        "visual": "雨に沈む無人の未来都市。濡れた路面に消えかけたネオンが反射し、遠景に白い小型探索ロボットのノアが立つ。",
        "action": "ノアが足を止め、水たまりのそばにあるかすかな光に気づく。",
        "camera": "ゆっくり前進するワイドショット",
        "emotion": "孤独、静けさ",
        "energy": "low",
        "location": "LOC_RAIN_ALLEY",
        "characters": ["CHAR_NOA"],
        "props": [],
        "palette": "cool_muted",
        "motion": "slow_push_in",
        "audio": "雨と遠い風。ピアノの単音を一つだけ置き、余白を残す。",
    },
    {
        "visual": "水たまりのそばに青白く浮かぶ星のかけらルミナ。ノアの目に小さな光が映る。",
        "action": "ノアが両手を伸ばす。触れる直前にルミナが一度だけ明滅する。",
        "camera": "ノアの視線からルミナへ寄るクローズアップ",
        "emotion": "好奇心、予感",
        "energy": "low",
        "location": "LOC_RAIN_ALLEY",
        "characters": ["CHAR_NOA"],
        "props": ["ITEM_LUMINA"],
        "palette": "cool_muted",
        "motion": "measured_tracking",
        "audio": "ガラスのような高音と柔らかな電子音。ピアノに短い上行音型を加える。",
    },
    {
        "visual": "ノアがルミナを両手で包む。胸の星形ランプが一瞬だけ反応する。",
        "action": "ルミナの光がノアの内部へ流れ、遠くの街灯が一つ点灯する。",
        "camera": "手元のクローズアップから胸部ランプへラックフォーカス",
        "emotion": "驚き、ぬくもり",
        "energy": "medium",
        "location": "LOC_RAIN_ALLEY",
        "characters": ["CHAR_NOA"],
        "props": ["ITEM_LUMINA"],
        "palette": "neutral_warm",
        "motion": "decisive_reveal",
        "audio": "低いパルスと柔らかな弦。光の流れに短い音楽アクセントを同期する。",
    },
    {
        "visual": "一つの街灯から隣の灯りへ光が連鎖する。雨粒が光を反射し、暗かった窓にも灯りが戻る。",
        "action": "街の灯りが少しずつ広がり、路地の輪郭が見えるようになる。",
        "camera": "路地から都市全景へ滑らかに引く",
        "emotion": "希望、つながり",
        "energy": "high",
        "location": "LOC_RAIN_ALLEY",
        "characters": ["CHAR_NOA"],
        "props": ["ITEM_LUMINA"],
        "palette": "accent_saturated",
        "motion": "slow_pull_back",
        "audio": "ピアノ主題を弦と柔らかなシンセで広げ、点灯に控えめなアクセントを置く。",
    },
    {
        "visual": "ノアが空を見上げる。雲の切れ間に星が一つだけ見え、胸のランプが同じリズムで明滅する。",
        "action": "ノアが小さく一歩踏み出す。暗転せず、光の余韻を残して終える。",
        "camera": "ノアの背後から空へティルトアップ",
        "emotion": "希望、謎、次への期待",
        "energy": "low",
        "location": "LOC_RAIN_ALLEY",
        "characters": ["CHAR_NOA"],
        "props": ["ITEM_LUMINA"],
        "palette": "warm_resolved",
        "motion": "slow_pull_back",
        "audio": "ピアノ主題を一音に収束。雨音を残し、短い残響で次話へつなぐ。",
    },
)


def build_star_night_scenario() -> dict[str, Any]:
    """Build the episode's five authored beats as a validated 15-second scenario."""
    scenario = build_scenario(
        "星を拾った夜",
        title="星を拾った夜 — 第1話",
        genre="静かなSFファンタジー",
        audience="一般視聴者・物語ゲームのプレイヤー",
        tone="静謐、切なさ、希望",
        premise="記憶を失った探索ロボットのノアが星のかけらルミナを拾い、街へ光を返す",
        duration_seconds=15,
        scene_count=5,
    )
    for index, (scene, authored) in enumerate(zip(scenario["scenes"], _SCENES), start=1):
        scene["scene_id"] = f"SC{index:02d}"
        scene["visual_direction"] = authored["visual"]
        scene["action"] = authored["action"]
        scene["dialogue_or_narration"] = ""
        scene["audio_direction"] = authored["audio"]
        scene["transition"] = (
            "雨音と光の余韻を保って次のカットへ接続する"
            if index < 5 else "雨音を残し、星の光の余韻で終える"
        )
        scene["shot_plan"].update({
            "shot_size": ("wide" if index == 1 else "close_up" if index in (2, 3) else "wide"),
            "camera_motion": authored["motion"],
            "focal_subject": "ノアとルミナ",
            "lighting": "雨に反射する青白い光",
            "color_palette": authored["palette"],
            "composition_note": authored["camera"],
        })
        scene["music_sync"].update({
            "emotional_intent": authored["emotion"],
            "energy": authored["energy"],
            "cue_in_seconds": 0,
            "cue_out_seconds": 3,
            "sync_points": [
                {"at_seconds": 0, "event": "カット冒頭の環境音と音楽を合わせる"},
                {"at_seconds": 1, "event": "主要動作または光の変化に音楽を呼応させる"},
                {"at_seconds": 3, "event": "次のカットへ余韻を渡す"},
            ],
            "motif": "MOTIF_STAR: 3音の上行ピアノモチーフ",
            "mix_priority": "balanced",
        })
        scene["continuity"] = {
            "characters": authored["characters"],
            "props": authored["props"],
            "location": authored["location"],
            "wardrobe": [],
            "must_match_previous_scene": index > 1,
        }
    return scenario


def build_candidate(
    output_dir: str | Path, *, bpm: int = 76, render_animatic: bool = False
) -> dict[str, Any]:
    """Create one non-overwriting cloud candidate and its structural review."""
    scenario = build_star_night_scenario()
    result = create_audiovisual_production_bundle(
        scenario,
        output_dir,
        bpm=bpm,
        genre="静かなSFファンタジーのオリジナル劇伴",
        instrumentation="ピアノ、柔らかなパッド、控えめな弦、ガラス質の電子音",
        render_animatic=render_animatic,
    )
    root = Path(result["directory"])
    music_plan = json.loads((root / "music_plan.json").read_text(encoding="utf-8"))
    edl = json.loads((root / "edit_decision_list.json").read_text(encoding="utf-8"))
    storyboard = json.loads((root / "storyboard.json").read_text(encoding="utf-8"))
    if result["video_render_status"] == "rendered":
        storyboard["render_status"] = "rendered"
        storyboard["visual_asset_mode"] = "procedural_storyboard_blocking"
        frame_paths = (result.get("animatic") or {}).get("frame_paths", [])
        for index, panel in enumerate(storyboard["panels"]):
            panel["asset_status"] = "procedural_blocking_frame_rendered"
            if index < len(frame_paths):
                panel["frame_path"] = frame_paths[index]
        (root / "storyboard.json").write_text(
            json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    critic = review_audiovisual_draft(scenario, music_plan, edl, storyboard)
    (root / "critic_review.json").write_text(
        json.dumps(critic, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["critic_review"] = "critic_review.json"
    manifest["cloud_execution"] = True
    manifest["video_render_status"] = result["video_render_status"]
    manifest["video_render_note"] = (
        "Procedural storyboard animatic only; this is not final character animation or AI-generated footage."
        if result["video_render_status"] == "rendered"
        else "No MP4 was generated. A cloud renderer and rights-cleared visual assets are separate prerequisites."
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "candidate_created",
        "directory": str(root),
        "artifact_names": sorted(manifest["artifacts"]),
        "midi_status": result["midi"]["status"],
        "audio_status": result["audio_render_status"],
        "video_status": result["video_render_status"],
        "video_path": result["video"]["path"] if result.get("video") else None,
        "critic_status": critic["status"],
        "publication_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--bpm", type=int, default=76)
    parser.add_argument(
        "--render-animatic",
        action="store_true",
        help="Render a procedural storyboard animatic with cloud-installed Blender and FFmpeg.",
    )
    args = parser.parse_args()
    result = build_candidate(
        args.output_dir, bpm=args.bpm, render_animatic=args.render_animatic
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
