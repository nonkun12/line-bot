"""Create a new, text-only Godot 4 narrative prototype from an approved design."""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")

def _scenes(design: object) -> list[dict[str, str]]:
    if not isinstance(design, dict) or design.get("schema_version") != "godot-game-design.v1":
        raise ValueError("design must use godot-game-design.v1")
    if not isinstance(design.get("approved_candidate_id"), str) or not design["approved_candidate_id"].strip():
        raise ValueError("approved candidate is required")
    if design.get("engine") != "Godot" or design.get("target_platform") not in {"desktop", "web"}:
        raise ValueError("unsupported Godot target")
    policy = design.get("safety_policy")
    if not isinstance(policy, dict) or policy.get("design_only") is not True or policy.get("automatic_publication") is not False:
        raise ValueError("design approval policy is invalid")
    source = design.get("scene_mapping")
    if not isinstance(source, list) or not 1 <= len(source) <= 40:
        raise ValueError("design must contain 1..40 scenes")
    result, seen = [], set()
    for item in source:
        if not isinstance(item, dict):
            raise ValueError("scene mapping must contain objects")
        sid, intent = item.get("scene_id"), item.get("story_intent")
        feedback = item.get("player_feedback", {})
        if not isinstance(sid, str) or not _ID.fullmatch(sid) or sid in seen:
            raise ValueError("scene IDs must be valid and unique")
        if not isinstance(intent, str) or not intent.strip() or len(intent) > 2000:
            raise ValueError("scene story intent is invalid")
        if not isinstance(feedback, dict):
            raise ValueError("player feedback must be an object")
        visual, music = feedback.get("visual", ""), feedback.get("audio", "")
        if not isinstance(visual, str) or not isinstance(music, str) or len(visual) > 1000 or len(music) > 1000:
            raise ValueError("scene feedback is invalid")
        seen.add(sid)
        result.append({"scene_id": sid, "story_intent": intent.strip(), "visual_motif": visual, "music_motif": music})
    return result

_ASSET_EXTENSIONS = {
    "audio": {".wav", ".ogg", ".mp3"},
    "image": {".png", ".jpg", ".jpeg", ".webp"},
    "video": {".ogv"},
}

def _approved_assets(design_scenes: list[dict[str, str]], manifest: object | None) -> dict[str, dict[str, str]]:
    if manifest is None:
        return {}
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "godot-approved-assets.v1":
        raise ValueError("asset manifest must use godot-approved-assets.v1")
    if manifest.get("human_approved") is not True or manifest.get("publication_authorized") is not False:
        raise ValueError("assets require explicit human approval and publication must remain unauthorized")
    entries = manifest.get("scenes")
    if not isinstance(entries, list) or len(entries) > 40:
        raise ValueError("asset manifest scenes must be a list of at most 40 items")
    known = {scene["scene_id"] for scene in design_scenes}
    result: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("asset manifest entries must be objects")
        sid = entry.get("scene_id")
        if not isinstance(sid, str) or sid not in known or sid in result:
            raise ValueError("asset manifest contains an unknown or duplicate scene ID")
        approval_note = entry.get("approval_note")
        if not isinstance(approval_note, str) or not approval_note.strip() or len(approval_note) > 500:
            raise ValueError("each asset entry requires a concise approval note")
        normalized: dict[str, str] = {}
        for kind in ("audio", "image", "video"):
            path = entry.get(f"{kind}_path")
            if path is None:
                continue
            if not isinstance(path, str) or not path.startswith("res://assets/") or len(path) > 240:
                raise ValueError(f"{kind}_path must be a project-local res://assets path")
            relative = path[len("res://assets/"):]
            parts = relative.split("/")
            if not relative or any(part in {"", ".", ".."} for part in parts) or not re.fullmatch(r"[A-Za-z0-9._/-]+", relative):
                raise ValueError(f"{kind}_path contains an unsafe path segment")
            if Path(relative).suffix.lower() not in _ASSET_EXTENSIONS[kind]:
                raise ValueError(f"unsupported {kind} asset extension")
            normalized[f"{kind}_path"] = path
        if normalized:
            result[sid] = normalized
    return result

def build_godot_project_files(design: object, approved_assets: object | None = None) -> dict[str, str]:
    """Build a deterministic file map; no filesystem or network side effects."""
    scenes = _scenes(design)
    asset_map = _approved_assets(scenes, approved_assets)
    for item in scenes:
        item.update(asset_map.get(item["scene_id"], {}))
    story = json.dumps({"schema_version": "godot-prototype-story.v1", "scenes": scenes}, ensure_ascii=False, indent=2) + "\n"
    project = """; Generated Godot 4 project
config_version=5

[application]
config/name="Story Harmony Prototype"
run/main_scene="res://scenes/main.tscn"

[display]
window/size/viewport_width=1280
window/size/viewport_height=720
window/size/window_width_override=1280
window/size/window_height_override=720

[rendering]
renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
"""
    scene = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/main.gd" id="1_main"]

[node name="Main" type="Control"]
layout_mode = 3
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
grow_horizontal = 2
grow_vertical = 2
script = ExtResource("1_main")

[node name="Margin" type="MarginContainer" parent="."]
layout_mode = 1
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
offset_left = 64.0
offset_top = 48.0
offset_right = -64.0
offset_bottom = -48.0
grow_horizontal = 2
grow_vertical = 2

[node name="Panel" type="PanelContainer" parent="Margin"]
layout_mode = 2

[node name="Layout" type="VBoxContainer" parent="Margin/Panel"]
layout_mode = 2
theme_override_constants/separation = 24

[node name="Title" type="Label" parent="Margin/Panel/Layout"]
layout_mode = 2
theme_override_font_sizes/font_size = 34
text = "Story Harmony"

[node name="Progress" type="Label" parent="Margin/Panel/Layout"]
layout_mode = 2
text = "Scene 1"

[node name="Intent" type="RichTextLabel" parent="Margin/Panel/Layout"]
custom_minimum_size = Vector2(0, 180)
layout_mode = 2
bbcode_enabled = true
fit_content = true
scroll_active = false

[node name="VisualMotif" type="Label" parent="Margin/Panel/Layout"]
layout_mode = 2
autowrap_mode = 3

[node name="MusicMotif" type="Label" parent="Margin/Panel/Layout"]
layout_mode = 2
autowrap_mode = 3

[node name="Advance" type="Button" parent="Margin/Panel/Layout"]
custom_minimum_size = Vector2(0, 56)
layout_mode = 2
text = "次のシーンへ"
"""
    main_script = '''extends Control

const AudioController = preload("res://scripts/audio_controller.gd")
const VisualController = preload("res://scripts/visual_controller.gd")
const STORY_PATH := "res://data/story.json"
@onready var title_label: Label = $Margin/Panel/Layout/Title
@onready var progress_label: Label = $Margin/Panel/Layout/Progress
@onready var intent_label: RichTextLabel = $Margin/Panel/Layout/Intent
@onready var visual_label: Label = $Margin/Panel/Layout/VisualMotif
@onready var music_label: Label = $Margin/Panel/Layout/MusicMotif
@onready var advance_button: Button = $Margin/Panel/Layout/Advance
@onready var layout: VBoxContainer = $Margin/Panel/Layout

var story_scenes: Array[Dictionary] = []
var current_index := 0
var audio_controller := AudioController.new()
var visual_controller := VisualController.new()

func _ready() -> void:
    add_child(audio_controller)
    add_child(visual_controller)
    advance_button.pressed.connect(_advance_scene)
    _load_story()

func _load_story() -> void:
    if not FileAccess.file_exists(STORY_PATH):
        _show_error("story.json が見つかりません")
        return
    var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(STORY_PATH))
    if not parsed is Dictionary or not parsed.get("scenes") is Array:
        _show_error("ストーリーデータの形式が不正です")
        return
    for item in parsed["scenes"]:
        if item is Dictionary and item.has("scene_id") and item.has("story_intent"):
            story_scenes.append(item)
    if story_scenes.is_empty():
        _show_error("シーンがありません")
        return
    _show_scene()

func _show_scene() -> void:
    var item := story_scenes[current_index]
    title_label.text = "Story Harmony"
    progress_label.text = "Scene %d / %d  ·  %s" % [current_index + 1, story_scenes.size(), item["scene_id"]]
    intent_label.text = str(item["story_intent"])
    visual_label.text = "VISUAL  ·  " + str(item.get("visual_motif", ""))
    music_label.text = "MUSIC  ·  " + str(item.get("music_motif", ""))
    advance_button.text = "物語を完了" if current_index == story_scenes.size() - 1 else "次のシーンへ"
    audio_controller.request_scene_cue(str(item["scene_id"]), str(item.get("music_motif", "")), str(item.get("audio_path", "")))
    visual_controller.show_scene(item, layout)

func _advance_scene() -> void:
    if current_index + 1 >= story_scenes.size():
        progress_label.text = "Prototype complete"
        advance_button.disabled = true
        audio_controller.stop()
        visual_controller.stop()
        return
    current_index += 1
    _show_scene()

func _show_error(message: String) -> void:
    title_label.text = "Prototype setup error"
    intent_label.text = message
    advance_button.disabled = true
'''
    audio_script = '''extends Node
## Plays only explicitly approved local audio paths supplied by the asset manifest.
signal scene_cue_requested(scene_id: String, music_motif: String)

var player := AudioStreamPlayer.new()

func _ready() -> void:
    add_child(player)
    player.bus = "Master"

func request_scene_cue(scene_id: String, music_motif: String, audio_path: String = "") -> void:
    stop()
    scene_cue_requested.emit(scene_id, music_motif)
    if audio_path.is_empty():
        return
    if not audio_path.begins_with("res://assets/") or ".." in audio_path:
        push_warning("Rejected unsafe audio asset path for scene: " + scene_id)
        return
    if not ResourceLoader.exists(audio_path):
        push_warning("Approved audio asset is missing: " + audio_path)
        return
    var stream: AudioStream = load(audio_path)
    if stream == null:
        push_warning("Could not load approved audio asset: " + audio_path)
        return
    player.stream = stream
    player.play()

func stop() -> void:
    if is_instance_valid(player):
        player.stop()
'''
    visual_script = '''extends Node
## Displays only explicitly approved local image or Ogg Theora video assets.

var image_node: TextureRect
var video_node: VideoStreamPlayer

func show_scene(item: Dictionary, parent_layout: VBoxContainer) -> void:
    stop()
    if image_node == null:
        image_node = TextureRect.new()
        image_node.name = "ApprovedSceneImage"
        image_node.custom_minimum_size = Vector2(0, 220)
        image_node.expand_mode = TextureRect.EXPAND_FIT_WIDTH_PROPORTIONAL
        image_node.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
        parent_layout.add_child(image_node)
        parent_layout.move_child(image_node, 3)
    var image_path := str(item.get("image_path", ""))
    if _safe_asset_path(image_path) and ResourceLoader.exists(image_path):
        var texture: Texture2D = load(image_path)
        if texture != null:
            image_node.texture = texture
            image_node.visible = true
        else:
            image_node.visible = false
    else:
        image_node.texture = null
        image_node.visible = false

    var video_path := str(item.get("video_path", ""))
    if _safe_asset_path(video_path) and ResourceLoader.exists(video_path):
        if video_node == null:
            video_node = VideoStreamPlayer.new()
            video_node.name = "ApprovedSceneVideo"
            video_node.custom_minimum_size = Vector2(0, 240)
            parent_layout.add_child(video_node)
            parent_layout.move_child(video_node, 4)
        var stream: VideoStream = load(video_path)
        if stream != null:
            video_node.stream = stream
            video_node.visible = true
            video_node.play()

func _safe_asset_path(path: String) -> bool:
    return path.begins_with("res://assets/") and not ".." in path and not path.contains(char(92))

func stop() -> void:
    if image_node != null:
        image_node.texture = null
        image_node.visible = false
    if video_node != null:
        video_node.stop()
        video_node.visible = false
'''
    readme = """# Story Harmony — Godot prototype

Requires Godot 4.x. Open this folder in Godot and press F5. Advance through
the approved story scenes to reach the prototype ending.

The prototype preserves scene IDs, story intent, visual motifs and music motifs.
Each scene transition emits a scene-linked audio cue signal. It uses no network,
paid service, downloaded asset or external runtime dependency.

This is a first playable narrative loop, not final art or final sound. The audio
controller emits a cue signal but does not play music. Integrate only approved
local audio assets in a later reviewed step. No media assets are copied or
modified. Existing output directories are never overwritten.
"""
    return {
        "project.godot": project,
        "scenes/main.tscn": scene,
        "scripts/main.gd": main_script,
        "scripts/audio_controller.gd": audio_script,
        "scripts/visual_controller.gd": visual_script,
        "data/story.json": story,
        "README.md": readme,
    }

def generate_godot_project(design: object, output_dir: str | Path, approved_assets: object | None = None) -> dict[str, Any]:
    """Create a brand-new project directory, refusing existing destinations."""
    files = build_godot_project_files(design, approved_assets)
    destination = Path(output_dir).expanduser()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("output directory already exists; refusing to overwrite")
    parent = destination.parent.resolve()
    if not parent.is_dir():
        raise FileNotFoundError("output parent directory must already exist")
    destination = parent / destination.name
    if destination.name in {"", ".", ".."}:
        raise ValueError("output directory name is invalid")
    destination.mkdir(mode=0o700)
    written: list[str] = []
    try:
        for relative, content in files.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            written.append(relative)
    except Exception:
        for relative in reversed(written):
            (destination / relative).unlink(missing_ok=True)
        for folder in sorted((p for p in destination.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            folder.rmdir()
        destination.rmdir()
        raise
    return {
        "status": "CREATED", "output_dir": str(destination),
        "files": sorted(written), "file_count": len(written),
        "assets_copied": False, "existing_files_overwritten": False,
        "network_used": False, "publication_authorized": False,
    }

__all__ = ["build_godot_project_files", "generate_godot_project"]
