"""Deterministic Blender storyboard animatic renderer.

Creates one procedural 3D frame per storyboard panel. These are visual
blocking frames, not final character animation or photographed footage.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


_BLENDER_SCRIPT = r"""
import bpy
import json
import math
import os
import sys
from pathlib import Path

args = sys.argv[sys.argv.index("--") + 1:]
source = Path(args[0])
destination = Path(args[1])
data = json.loads(source.read_text(encoding="utf-8"))
panels = data["panels"]

def material(name, color):
    mat = bpy.data.materials.new(name)
    rgba = (*color, 1.0)
    mat.diffuse_color = rgba
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    if shader is not None:
        shader.inputs["Base Color"].default_value = rgba
        shader.inputs["Roughness"].default_value = 0.82
    return mat

def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in bpy.data.materials:
        bpy.data.materials.remove(block)

def wrap_caption(value, width):
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return "\n".join(text[offset:offset + width] for offset in range(0, len(text), width))


def add_caption(body, name, location, size, font=None):
    if not body:
        return
    curve = bpy.data.curves.new(name, type="FONT")
    curve.body = body
    curve.size = size
    curve.align_x = "LEFT"
    curve.align_y = "CENTER"
    if font is not None:
        curve.font = font
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    curve.extrude = 0.001
    curve.materials.append(material(name + " material", (0.96, 0.97, 1.0)))

font = None
for font_path in (
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
):
    if os.path.isfile(font_path):
        try:
            font = bpy.data.fonts.load(font_path)
            break
        except Exception:
            font = None

for index, panel in enumerate(panels, start=1):
    clear_scene()
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.025, 0.03, 0.06)

    palette = str(panel.get("color_palette", "")).lower()
    if "warm" in palette or "dawn" in palette:
        accent = (0.85, 0.38, 0.16)
    elif "saturated" in palette:
        accent = (0.15, 0.48, 0.85)
    elif "cool" in palette:
        accent = (0.12, 0.38, 0.62)
    else:
        accent = (0.42, 0.48, 0.58)
    base = material("Base", (0.025, 0.04, 0.075))
    highlight = material("Accent", accent)
    secondary = material("Secondary", (0.22, 0.32, 0.43))

    bpy.ops.mesh.primitive_plane_add(size=18, location=(0, 0, -0.5))
    bpy.context.object.name = "Storyboard background"
    bpy.context.object.data.materials.append(base)

    # Three visual layers create a simple composition block, not literal scene content.
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.15))
    subject = bpy.context.object
    subject.name = "Focal subject placeholder"
    subject.dimensions = (3.2, 2.2, 0.55)
    subject.data.materials.append(highlight)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.7,
                                         location=(1.35, 0.95, 0.7))
    bpy.context.object.data.materials.append(secondary)

    bpy.ops.object.camera_add(location=(0, 0, 12))
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 12
    scene.camera = camera
    camera.rotation_euler = (0, 0, 0)

    bpy.ops.object.light_add(type="AREA", location=(0, 2, 8))
    light = bpy.context.object
    light.data.energy = 1600
    light.data.shape = "DISK"
    light.data.size = 8

    # Burn in a readable title and narration subtitle. Japanese font is used
    # when present; Blender's bundled font remains a safe fallback.
    title = wrap_caption(str(panel.get("focal_subject", ""))[:48], 24)
    narration = wrap_caption(str(panel.get("dialogue_or_narration", ""))[:72], 24)
    add_caption(title, "Title", (-5.2, 4.35, 0.9), 0.42, font)
    add_caption(narration, "Narration", (-5.2, -4.35, 0.9), 0.28, font)

    scene.render.filepath = str(destination / ("scene_%02d.png" % index))
    bpy.ops.render.render(write_still=True)
"""


def render_storyboard_animatic(
    storyboard: dict[str, Any],
    output_dir: str | Path,
    *,
    blender_executable: str | None = None,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Render bounded, procedural storyboard blocking frames with Blender."""
    if not isinstance(storyboard, dict) or storyboard.get("schema_version") != "video-storyboard.v1":
        raise ValueError("storyboard must use video-storyboard.v1")
    panels = storyboard.get("panels")
    duration = storyboard.get("duration_seconds")
    if not isinstance(panels, list) or not 1 <= len(panels) <= 20:
        raise ValueError("storyboard must contain 1 to 20 panels")
    if type(duration) is not int or duration <= 0:
        raise ValueError("storyboard duration_seconds must be a positive integer")
    expected_start = 0
    for panel in panels:
        if not isinstance(panel, dict) or any(
            not isinstance(panel.get(key), str) or not panel[key].strip()
            for key in ("panel_id", "color_palette", "frame_description")
        ):
            raise ValueError("storyboard panel is incomplete")
        start = panel.get("time_start_seconds")
        length = panel.get("duration_seconds")
        if type(start) is not int or start != expected_start or type(length) is not int or length <= 0:
            raise ValueError("storyboard panel timeline must be contiguous and positive")
        expected_start = start + length
    if expected_start != duration:
        raise ValueError("storyboard panels must cover the declared duration")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 1800:
        raise ValueError("timeout_seconds must be between 1 and 1800")
    executable = blender_executable or shutil.which("blender")
    if not isinstance(executable, str) or not executable:
        raise RuntimeError("Blender is not installed; no storyboard frames were rendered")

    destination = Path(output_dir).expanduser()
    if destination.exists():
        raise FileExistsError(str(destination))
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with tempfile.TemporaryDirectory(prefix="line-bot-blender-") as temp:
            root = Path(temp)
            storyboard_file = root / "storyboard.json"
            script_file = root / "render.py"
            storyboard_file.write_text(
                json.dumps(storyboard, ensure_ascii=False), encoding="utf-8"
            )
            script_file.write_text(_BLENDER_SCRIPT, encoding="utf-8")
            completed = subprocess.run(
                [executable, "--background", "--factory-startup", "--python",
                 str(script_file), "--", str(storyboard_file), str(destination.resolve())],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=timeout_seconds, check=False,
            )
        frames = sorted(destination.glob("scene_*.png"))
        if completed.returncode != 0 or len(frames) != len(panels) or any(
            frame.is_symlink() or frame.stat().st_size <= 0 for frame in frames
        ):
            detail = (completed.stderr or completed.stdout or "Blender produced incomplete frames")[-1200:]
            raise RuntimeError(f"Blender storyboard rendering failed: {detail}")
        return {
            "status": "rendered",
            "renderer": "Blender",
            "frame_count": len(frames),
            "resolution": "1280x720",
            "frame_paths": [str(frame) for frame in frames],
            "visual_mode": "procedural_storyboard_blocking",
            "final_animation": False,
        }
    except Exception:
        for frame in destination.glob("scene_*.png"):
            if frame.is_file() and not frame.is_symlink():
                frame.unlink()
        destination.rmdir()
        raise


__all__ = ["render_storyboard_animatic"]
