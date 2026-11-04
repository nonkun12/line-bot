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


def _analyze_reachability(start_node: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """Traverse the declared directed graph; never trust precomputed reachability claims."""
    node_ids = [node.get("id") for node in nodes]
    unique_ids = len(node_ids) == len(set(node_ids)) and all(isinstance(x, str) and x for x in node_ids)
    declared = set(node_ids)
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in declared}
    invalid_edges = []
    for edge in edges:
        source, target = edge.get("source_node"), edge.get("next_node")
        if source not in declared or target not in declared:
            invalid_edges.append(edge.get("id", "<unknown>"))
        else:
            adjacency[source].append(target)
    reachable: set[str] = set()
    if start_node in declared:
        pending = [start_node]
        while pending:
            current = pending.pop()
            if current in reachable:
                continue
            reachable.add(current)
            pending.extend(adjacency[current])
    unreachable = sorted(declared - reachable)
    return {
        "start_node_declared": start_node in declared,
        "node_ids_unique": unique_ids,
        "invalid_edges": invalid_edges,
        "reachable_nodes": sorted(reachable),
        "unreachable_nodes": unreachable,
        "all_nodes_reachable": bool(unique_ids and start_node in declared and not invalid_edges and not unreachable),
    }


def _build_hourly_focus_artifact(task_id: str) -> tuple[str, dict[str, Any]]:
    """Create one substantive, editable deliverable for the selected hourly focus."""
    deliverables: dict[str, tuple[str, dict[str, Any]]] = {
        "continuity": ("continuity_sheet.json", {
            "focus_id": task_id, "version": 1,
            "characters": [
                {"id": "CHAR_NOA", "silhouette": "小柄な丸い頭と短い胴体の探索ロボット",
                 "fixed_features": ["胸の星形ランプ", "青灰色の外装", "淡いシアンの目"],
                 "emotional_range": ["警戒", "好奇心", "小さな勇気"]},
                {"id": "CHAR_LUMINA", "silhouette": "青白い光を放つ小さな星形のかけら",
                 "fixed_features": ["中心は白に近い青", "外周に淡い水色の光輪"],
                 "behavior_rule": "感情を言葉で説明せず、明滅と光量で反応する"},
            ],
            "environment": {"id": "LOC_RAIN_ALLEY", "weather": "小雨",
                            "palette_transition": "冷たい青から灯りの琥珀色へ"},
        }),
        "episode_002": ("episode_002_outline.json", {
            "focus_id": task_id, "episode_id": "SN-E002", "title": "旧駅の案内機",
            "logline": "ノアは旧駅で、街の灯りが消えた理由を知る案内機と出会う。",
            "beats": [
                {"id": "E2-B01", "beat": "旧駅の入口で、ルミナに反応する案内板を見つける"},
                {"id": "E2-B02", "beat": "案内機ミナが起動するが、記憶の一部が欠けている"},
                {"id": "E2-B03", "beat": "ノアは案内機の記憶か、駅の非常灯か、ミナとの信頼を優先する"},
                {"id": "E2-B04", "beat": "選択に応じて旧駅の出口と次の探索地点が変化する"},
            ],
            "choices": ["CHOICE_MEMORY", "CHOICE_LIGHTS", "CHOICE_TRUST"],
            "canon_status": "proposal_only",
        }),
        "branch_graph": ("branch_reachability.json", {
            "focus_id": task_id, "start_node": "NODE_START", "initial_state": {"trust_mina": 0, "city_lights": 0, "noa_memory": 0},
            "branches": [
                {"id": "CHOICE_LUMINA_01A", "source_node": "NODE_START", "state_delta": {"noa_memory": 1}, "next_node": "NODE_MEMORY"},
                {"id": "CHOICE_LUMINA_01B", "source_node": "NODE_START", "state_delta": {"city_lights": 1}, "next_node": "NODE_LIGHTS"},
                {"id": "CHOICE_LUMINA_01C", "source_node": "NODE_START", "state_delta": {"trust_mina": 1}, "next_node": "NODE_TRUST"},
            ],
            "nodes": [
                {"id": "NODE_START", "type": "choice", "description": "ルミナをどう使うか選ぶ"},
                {"id": "NODE_MEMORY", "outcome": "ノアの記憶を優先し、旧駅の記録区画を解放", "unlocks": "LOC_OLD_STATION_ARCHIVE"},
                {"id": "NODE_LIGHTS", "outcome": "街の非常灯を優先し、暗い通路を照らす", "unlocks": "LOC_OLD_STATION_TUNNEL"},
                {"id": "NODE_TRUST", "outcome": "ミナとの信頼を優先し、案内機の協力を得る", "unlocks": "LOC_OLD_STATION_CONTROL"},
            ],
            "validation": "breadth_first_graph_traversal",
        }),
        "visual_design": ("visual_design.json", {
            "focus_id": task_id, "global_style": "雨の青を基調に、光だけを暖色で際立たせる",
            "cuts": [
                {"scene_id": scene["id"], "composition": scene["camera"],
                 "palette": ["deep_navy", "rain_blue", "lumina_cyan"],
                 "lighting": "ルミナを主光源にし、濡れた路面へ細い反射を落とす"}
                for scene in SCENES
            ],
        }),
        "music_variation": ("music_variations.json", {
            "focus_id": task_id, "motif": "MOTIF_STAR", "tempo_bpm": 76,
            "variations": [
                {"scene_id": "SC01", "notes": ["C4"], "texture": "遠い単音、長い余韻"},
                {"scene_id": "SC02", "notes": ["D4", "G4"], "texture": "問いかける二音"},
                {"scene_id": "SC03", "notes": ["C4", "D4", "G4"], "texture": "星の三音を明確に提示"},
                {"scene_id": "SC04", "notes": ["G4", "C5", "D5"], "texture": "街灯の連鎖に合わせて上昇"},
                {"scene_id": "SC05", "notes": ["G4", "D4"], "texture": "静かに余韻を残す"},
            ],
            "production_note": "次工程で弦とパッドを加える候補。現行WAVは単純な合成プレビュー。",
        }),
        "game_loop": ("game_loop_design.json", {
            "focus_id": task_id,
            "loop": ["探索", "手がかり発見", "修理・謎解き", "キャラクターとの対話",
                     "選択", "街・関係性の状態変化", "新しい場所の解放"],
            "state_variables": ["trust_mina", "city_lights", "noa_memory",
                                "lumina_fragments", "discovered_locations", "choice_history"],
            "player_feedback": "選択結果を街の灯り・案内機の応答・探索可能範囲で見せる",
        }),
    }
    if task_id not in deliverables:
        raise ValueError(f"Unknown hourly focus: {task_id}")
    filename, payload = deliverables[task_id]
    if task_id == "branch_graph":
        payload["reachability"] = _analyze_reachability(
            payload["start_node"], payload["nodes"], payload["branches"]
        )
    return filename, payload


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


def _render_animatic(destination: Path) -> Path:
    """Render a 15-second illustrated storyboard animatic with local open tools."""
    import shutil
    import subprocess

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Pillow is required for animatic rendering") from exc
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for animatic rendering")

    width, height = 1280, 720
    frame_dir = destination / "animatic_frames"
    frame_dir.mkdir(exist_ok=True)
    font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    bold_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    def font(size: int, bold: bool = False):
        candidate = bold_path if bold else font_path
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            return ImageFont.load_default()

    titles = ["雨の街", "星のかけら", "小さな選択", "街に戻る光", "胸に残る星"]
    captions = [
        "雨に沈む街で、ノアは小さな光に気づく",
        "水たまりのそばに、星のかけらルミナ",
        "誰かのための光が、最初の灯りになる",
        "ひとつの灯りが、街へと広がっていく",
        "雲の向こうに星。ノアの胸にも小さな光",
    ]
    durations = [scene["duration"] for scene in SCENES]
    for index, scene in enumerate(SCENES):
        image = Image.new("RGB", (width, height), (8, 16, 34))
        pixels = image.load()
        for y in range(height):
            blend = y / height
            color = (int(10 + 10 * blend), int(22 + 18 * blend), int(48 + 25 * blend))
            for x in range(width):
                pixels[x, y] = color
        draw = ImageDraw.Draw(image, "RGBA")

        # Distant skyline and wet street, built from simple graphic shapes.
        for b in range(9):
            x = b * 155 - 20
            top = 205 + ((b * 37) % 110)
            draw.rectangle((x, top, x + 115, 570), fill=(15, 29, 54, 235), outline=(48, 76, 112, 150), width=2)
            for wy in range(top + 24, 535, 42):
                for wx in range(x + 18, x + 100, 30):
                    lit = index >= 3 and ((b + wy + wx) % 4 == 0)
                    draw.rectangle((wx, wy, wx + 8, wy + 13),
                                   fill=(255, 204, 125, 190) if lit else (45, 78, 112, 100))
        draw.polygon([(0, 560), (width, 520), (width, height), (0, height)], fill=(12, 20, 34, 255))
        for r in range(14):
            y = 575 + r * 12
            draw.line((0, y, width, y - 34), fill=(70, 104, 145, 65), width=2)
        # Rain strokes.
        for r in range(95):
            x = (r * 137 + index * 29) % width
            y = (r * 83 + index * 41) % 570
            draw.line((x, y, x - 8, y + 23), fill=(140, 190, 225, 95), width=2)

        # Small explorer robot silhouette, consistent across all shots.
        robot_x = 475 if index < 3 else 560
        robot_y = 478
        draw.ellipse((robot_x - 42, robot_y - 104, robot_x + 42, robot_y - 20),
                     fill=(91, 132, 158, 255), outline=(185, 215, 224, 255), width=4)
        draw.rounded_rectangle((robot_x - 55, robot_y - 24, robot_x + 55, robot_y + 88),
                               radius=25, fill=(62, 101, 127, 255), outline=(185, 215, 224, 255), width=4)
        draw.ellipse((robot_x - 18, robot_y - 75, robot_x - 4, robot_y - 61), fill=(125, 226, 255, 255))
        draw.ellipse((robot_x + 4, robot_y - 75, robot_x + 18, robot_y - 61), fill=(125, 226, 255, 255))
        draw.ellipse((robot_x - 16, robot_y + 10, robot_x + 16, robot_y + 42),
                     fill=(255, 221, 130, 230) if index >= 2 else (90, 125, 151, 255))

        # Lumina moves from the ground to the robot and then the city.
        lumina_x = [700, 700, 625, 820, 820][index]
        lumina_y = [530, 525, 420, 320, 245][index]
        glow = 26 if index < 3 else 42
        draw.ellipse((lumina_x - glow * 2, lumina_y - glow * 2,
                      lumina_x + glow * 2, lumina_y + glow * 2), fill=(78, 190, 255, 35))
        draw.ellipse((lumina_x - glow, lumina_y - glow, lumina_x + glow, lumina_y + glow),
                     fill=(112, 218, 255, 105), outline=(210, 247, 255, 230), width=3)
        # Star glyph.
        draw.text((lumina_x, lumina_y), "✦", font=font(58, True), fill=(255, 246, 198, 255), anchor="mm")
        if index >= 3:
            for lx in [160, 330, 1020, 1150]:
                draw.ellipse((lx - 13, 300, lx + 13, 326), fill=(255, 210, 132, 220))
                draw.line((lx, 326, lx, 505), fill=(255, 210, 132, 160), width=5)
        if index == 4:
            draw.ellipse((965, 92, 1000, 127), fill=(255, 245, 207, 245))
            draw.ellipse((950, 78, 1015, 141), outline=(255, 232, 172, 140), width=3)

        # Title plate and lower caption.
        draw.rounded_rectangle((55, 45, 490, 132), radius=18, fill=(5, 13, 28, 190),
                               outline=(122, 176, 211, 100), width=2)
        draw.text((82, 63), "星を拾った夜", font=font(39, True), fill=(235, 245, 255, 255))
        draw.text((84, 112), f"EPISODE 01  /  CUT 0{index + 1}", font=font(15), fill=(151, 195, 224, 255))
        draw.rounded_rectangle((55, 620, 1225, 685), radius=14, fill=(4, 11, 24, 205))
        draw.text((82, 638), captions[index], font=font(25), fill=(236, 243, 251, 255))
        draw.text((1190, 92), titles[index], font=font(22), fill=(190, 222, 245, 230), anchor="ra")
        image.save(frame_dir / f"cut_{index + 1:02d}.png", optimize=True)

    concat_file = frame_dir / "frames.txt"
    lines = []
    for index, duration in enumerate(durations, start=1):
        lines.extend([f"file 'cut_{index:02d}.png'", f"duration {duration}"])
    lines.append(f"file 'cut_{len(durations):02d}.png'")
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output = destination / "star-night-episode-01-animatic.mp4"
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(destination / "original_music.wav"),
        "-vf", "fps=24,format=yuv420p", "-t", "15",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "160k", "-shortest",
        "-movflags", "+faststart", str(output),
    ]
    subprocess.run(command, cwd=frame_dir, check=True, capture_output=True, text=True)
    if not output.is_file() or output.stat().st_size < 10_000:
        raise RuntimeError("ffmpeg did not produce a valid animatic")
    return output


def build_candidate(output_dir: str | Path, *, now: datetime | None = None, render_animatic: bool = False) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    stamp = moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = Path(output_dir).resolve()
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
                 "status": "draft", "start_node": "NODE_START", "initial_state": {"trust_mina": 0, "city_lights": 0, "noa_memory": 0},
                 "nodes": [
                     {"id": "NODE_START", "type": "choice", "description": "ルミナをどう使うか選ぶ"},
                     {"id": "NODE_MEMORY", "outcome": "ノアの記憶を優先し、旧駅の記録区画を解放", "unlocks": "LOC_OLD_STATION_ARCHIVE"},
                     {"id": "NODE_LIGHTS", "outcome": "街の非常灯を優先し、暗い通路を照らす", "unlocks": "LOC_OLD_STATION_TUNNEL"},
                     {"id": "NODE_TRUST", "outcome": "ミナとの信頼を優先し、案内機の協力を得る", "unlocks": "LOC_OLD_STATION_CONTROL"},
                 ],
                 "choices": [{"id": "CHOICE_LUMINA_01A", "source_node": "NODE_START", "effect": {"noa_memory": 1}, "next_node": "NODE_MEMORY"},
                             {"id": "CHOICE_LUMINA_01B", "source_node": "NODE_START", "effect": {"city_lights": 1}, "next_node": "NODE_LIGHTS"},
                             {"id": "CHOICE_LUMINA_01C", "source_node": "NODE_START", "effect": {"trust_mina": 1}, "next_node": "NODE_TRUST"}]}
        task_index = int(moment.timestamp() // 3600) % len(TASKS)
        task_id, task_title = TASKS[task_index]
        task = {"task_id": f"SN-HOURLY-{stamp}", "focus": task_id, "proposal": task_title,
                "status": "candidate_only", "requires_critic_and_human_approval": True}
        focus_filename, focus_artifact = _build_hourly_focus_artifact(task_id)
        critic_checks = {
            "five_unique_scene_ids": len({s["id"] for s in SCENES}) == 5,
            "timeline_contiguous": all(SCENES[i]["start"] + SCENES[i]["duration"] == SCENES[i+1]["start"] for i in range(4)),
            "total_duration_15_seconds": sum(s["duration"] for s in SCENES) == 15,
            "all_scenes_have_location": all(s["location"] for s in SCENES),
            "choice_ids_unique": len({c["id"] for c in graph["choices"]}) == 3,
            "choice_targets_declared": all(c["next_node"] in {n["id"] for n in graph["nodes"]} for c in graph["choices"]),
            "choice_effect_keys_valid": all(set(c["effect"]).issubset(graph["initial_state"]) for c in graph["choices"]),
            "graph_reachability_valid": _analyze_reachability(graph["start_node"], graph["nodes"], graph["choices"])["all_nodes_reachable"]}
        critic = {
            "status": "PASS" if all(critic_checks.values()) else "FAIL",
            "checks": critic_checks,
        }
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
        (destination / focus_filename).write_text(
            json.dumps(focus_artifact, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (destination / "original_music.mid").write_bytes(_midi_bytes())
        _write_wav(destination / "original_music.wav")
        video_path = _render_animatic(destination) if render_animatic else None
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.iterdir()) if p.is_file()}
        manifest = {"schema_version": "star-night-candidate-manifest.v1", "created_at": moment.isoformat(),
                    "project_id": PROJECT, "episode_id": "SN-E001", "status": "draft",
                    "cloud_execution": True, "mac_required": False, "paid_api_used": False,
                    "video_render_status": "animatic_rendered" if video_path else "not_rendered", "publication_authorized": False,
                    "canon_modified": False, "hourly_task": task, "sha256": hashes}
        (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "candidate_created", "directory": str(destination), "artifact_count": len(hashes) + 1,
                "midi": "generated", "wav": "generated", "video": str(video_path) if video_path else "not_rendered",
                "task_focus": task_id, "publication_authorized": False}
    except Exception:
        import shutil
        shutil.rmtree(destination, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--render-animatic", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build_candidate(args.output_dir, render_animatic=args.render_animatic), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
