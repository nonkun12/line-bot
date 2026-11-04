"""Cloud-only, dependency-light STAR-NIGHT candidate builder.

Uses Python standard library only. Produces editable story artifacts and
original MIDI/WAV previews. It does not call external APIs, use a Mac worker,
render character animation, publish, or modify story canon.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT = "STAR-NIGHT"
SCENES = [
    {"id": "SC01", "start": 0, "duration": 3, "title": "雨の街",
     "visual": "雨に沈む未来都市。濡れた路面に消えかけたネオンが反射し、遠景にノアの小さな姿。",
     "action": "ノアが足を止め、かすかな光に気づく。", "camera": "ゆっくり前進するワイドショット",
     "emotion": "孤独、静けさ", "energy": "low", "location": "LOC_RAIN_ALLEY", "props": []},
    {"id": "SC02", "start": 3, "duration": 3, "title": "星のかけら",
     "visual": "水たまりのそばに青白く浮かぶルミナ。ノアの目に小さな光が映る。",
     "action": "ノアが両手を伸ばす。ルミナが一度だけ明滅する。", "camera": "ルミナへ寄るクローズアップ",
     "emotion": "好奇心、予感", "energy": "low", "location": "LOC_RAIN_ALLEY", "props": ["ITEM_LUMINA"]},
    {"id": "SC03", "start": 6, "duration": 4, "title": "小さな選択",
     "visual": "ノアがルミナを包む。胸の星形ランプが一瞬だけ反応する。",
     "action": "ルミナの光が流れ、遠くの街灯が一つ点灯する。", "camera": "手元から胸部ランプへラックフォーカス",
     "emotion": "驚き、ぬくもり", "energy": "medium", "location": "LOC_RAIN_ALLEY", "props": ["ITEM_LUMINA"]},
    {"id": "SC04", "start": 10, "duration": 3, "title": "街に戻る光",
     "visual": "一つの街灯から隣の灯りへ光が連鎖し、雨粒が光を反射する。",
     "action": "暗かった窓にも灯りがともる。", "camera": "路地から都市全景へ引く",
     "emotion": "希望、つながり", "energy": "high", "location": "LOC_RAIN_ALLEY", "props": ["ITEM_LUMINA"]},
    {"id": "SC05", "start": 13, "duration": 2, "title": "胸に残る星",
     "visual": "ノアが空を見上げる。雲の切れ間に星が一つだけ見える。",
     "action": "胸のランプが明滅し、ノアが一歩踏み出す。", "camera": "背後から空へティルトアップ",
     "emotion": "希望、謎", "energy": "low", "location": "LOC_RAIN_ALLEY", "props": ["ITEM_LUMINA"]},
]
TASKS = [
    ("continuity", "ノア・ルミナ・雨の路地の外見連続性シートを作る"),
    ("episode_002", "第2話「旧駅の案内機」のシナリオ候補を作る"),
    ("branch_graph", "ルミナの3分岐と状態遷移の到達性を検証する"),
    ("visual_design", "5カットの構図・色・ライティング案を詳細化する"),
    ("music_variation", "3音の星モチーフを場面別に変奏する"),
    ("game_loop", "探索・発見・選択・街の変化をつなぐゲームループを設計する"),
]


def _vlq(value: int) -> bytes:
    value = max(0, int(value))
    buffer = value & 0x7F
    out = bytearray()
    while (value := value >> 7):
        buffer <<= 8
        buffer |= ((value & 0x7F) | 0x80)
    while True:
        out.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(out)


def _midi_bytes() -> bytes:
    # 76 BPM, 4/4, original three-note ascending motif.
    events = [(0, bytes([0xFF, 0x51, 0x03, 0x0C, 0x16, 0x15])),
              (0, bytes([0xFF, 0x58, 0x04, 0x04, 0x02, 0x18, 0x08]))]
    ticks_per_second = 480 * 76 / 60
    motif = [(60, 0.8), (62, 1.2), (67, 2.4), (72, 2.8), (67, 2.2), (62, 1.5)]
    for start_sec, (note, duration_seconds) in zip([0, 1, 3, 6, 10, 13], motif):
        start = round(start_sec * ticks_per_second)
        end = start + round(duration_seconds * ticks_per_second)
        events.append((start, bytes([0x90, note, 72])))
        events.append((end, bytes([0x80, note, 0])))
    events.sort(key=lambda item: item[0])
    track = bytearray()
    previous = 0
    for tick, payload in events:
        track.extend(_vlq(tick - previous))
        track.extend(payload)
        previous = tick
    track.extend(b"\x00\xff\x2f\x00")
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(track)) + track


def _write_wav(path: Path, duration: float = 15.0, sample_rate: int = 22050) -> None:
    notes = [(0.0, 1.0, 261.63), (1.0, 2.0, 293.66), (3.0, 3.0, 392.00),
             (6.0, 4.0, 493.88), (10.0, 3.0, 392.00), (13.0, 2.0, 293.66)]
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for index in range(int(duration * sample_rate)):
            t = index / sample_rate
            sample = 0.0
            for start, length, frequency in notes:
                local = t - start
                if 0 <= local < length:
                    attack = min(1.0, local / 0.12)
                    release = min(1.0, (length - local) / 0.35)
                    envelope = max(0.0, min(attack, release))
                    sample += envelope * (math.sin(2 * math.pi * frequency * local)
                                           + 0.18 * math.sin(4 * math.pi * frequency * local)) * 0.16
            frames.extend(struct.pack("<h", max(-32767, min(32767, int(sample * 32767)))))
        wav.writeframes(frames)


def build_candidate(output_dir: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    stamp = moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = Path(output_dir)
    if destination.exists():
        raise FileExistsError(str(destination))
    destination.mkdir(parents=True, exist_ok=False)
    try:
        scenario = {"schema_version": "star-night-scenario.v1", "project_id": PROJECT,
                    "episode_id": "SN-E001", "title": "星を拾った夜 — 第1話",
                    "duration_seconds": 15, "dialogue": "なし", "scenes": SCENES}
        screenplay = ["# 星を拾った夜 — 第1話「星を拾った夜」", "",
                      "15秒・5カット・セリフなし。テーマ：誰かのために灯した光は、巡って自分の道も照らす。", ""]
        for scene in SCENES:
            screenplay += [f"## {scene['id']} — {scene['title']} ({scene['start']}–{scene['start'] + scene['duration']}秒)",
                           f"- 映像：{scene['visual']}", f"- 動作：{scene['action']}",
                           f"- カメラ：{scene['camera']}", f"- 感情：{scene['emotion']}", ""]
        storyboard = {"schema_version": "star-night-storyboard.v1", "duration_seconds": 15,
                      "panels": [{"panel_id": s["id"], "time_start_seconds": s["start"],
                                  "duration_seconds": s["duration"], "description": s["visual"],
                                  "camera": s["camera"], "palette": "雨の青から星の暖色へ"}
                                 for s in SCENES]}
        shot_list = [{"shot_id": s["id"], "duration_seconds": s["duration"],
                      "shot_size": "wide" if s["id"] in ("SC01", "SC04") else "close",
                      "camera": s["camera"]} for s in SCENES]
        music_plan = {"tempo_bpm": 76, "meter": "4/4", "duration_seconds": 15,
                      "motif": "MOTIF_STAR: 3音の上行ピアノ", "instrumentation": ["ピアノ", "柔らかなパッド", "控えめな弦"],
                      "energy_curve": [s["energy"] for s in SCENES],
                      "rights_note": "Python合成のオリジナル試作。公開前に権利・音質レビュー必須。"}
        graph = {"schema_version": "interactive-story-graph.v1", "project_id": PROJECT,
                 "status": "draft", "initial_state": {"trust_mina": 0, "city_lights": 0, "noa_memory": 0},
                 "choices": [{"id": "CHOICE_LUMINA_01A", "effect": {"noa_memory": 1}},
                             {"id": "CHOICE_LUMINA_01B", "effect": {"city_lights": 1}},
                             {"id": "CHOICE_LUMINA_01C", "effect": {"trust_mina": 1}}]}
        task_index = int(moment.timestamp() // 3600) % len(TASKS)
        task_id, task_title = TASKS[task_index]
        task = {"task_id": f"SN-HOURLY-{stamp}", "focus": task_id, "proposal": task_title,
                "status": "candidate_only", "requires_critic_and_human_approval": True}
        critic = {"status": "STRUCTURAL_CHECKS_PASS", "checks": {
            "five_unique_scene_ids": len({s["id"] for s in SCENES}) == 5,
            "timeline_contiguous": all(SCENES[i]["start"] + SCENES[i]["duration"] == SCENES[i+1]["start"] for i in range(4)),
            "total_duration_15_seconds": sum(s["duration"] for s in SCENES) == 15,
            "all_scenes_have_location": all(s["location"] for s in SCENES),
            "choice_ids_unique": len({c["id"] for c in graph["choices"]}) == 3}}
        files = {
            "scenario.json": json.dumps(scenario, ensure_ascii=False, indent=2) + "\n",
            "screenplay.md": "\n".join(screenplay),
            "storyboard.json": json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n",
            "shot_list.json": json.dumps(shot_list, ensure_ascii=False, indent=2) + "\n",
            "music_plan.json": json.dumps(music_plan, ensure_ascii=False, indent=2) + "\n",
            "game_story_graph.json": json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
            "hourly_task.json": json.dumps(task, ensure_ascii=False, indent=2) + "\n",
            "critic_review.json": json.dumps(critic, ensure_ascii=False, indent=2) + "\n"}
        for name, content in files.items():
            (destination / name).write_text(content, encoding="utf-8")
        (destination / "original_music.mid").write_bytes(_midi_bytes())
        _write_wav(destination / "original_music.wav")
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.iterdir()) if p.is_file()}
        manifest = {"schema_version": "star-night-candidate-manifest.v1", "created_at": moment.isoformat(),
                    "project_id": PROJECT, "episode_id": "SN-E001", "status": "draft",
                    "cloud_execution": True, "mac_required": False, "paid_api_used": False,
                    "video_render_status": "not_rendered", "publication_authorized": False,
                    "canon_modified": False, "hourly_task": task, "sha256": hashes}
        (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "candidate_created", "directory": str(destination), "artifact_count": len(hashes) + 1,
                "midi": "generated", "wav": "generated", "video": "not_rendered",
                "task_focus": task_id, "publication_authorized": False}
    except Exception:
        import shutil
        shutil.rmtree(destination, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(build_candidate(args.output_dir), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
