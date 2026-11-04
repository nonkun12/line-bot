"""Validate and resolve deterministic branching narrative graphs for Godot prototypes."""
from __future__ import annotations

import re
from collections import deque
from copy import deepcopy
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_MAX_SCENES = 40
_MAX_CHOICES = 4


def build_story_graph(scene_mapping: object, entry_scene_id: str | None = None) -> dict[str, Any]:
    """Normalize a scene mapping into a validated, reachable branching graph.

    A scene must have exactly one transition mode: one or more explicit choices,
    a single next_scene_id, or ending=True. Cycles are allowed for intentional
    gameplay loops; all scenes must nevertheless be reachable from the entry.
    """
    if not isinstance(scene_mapping, list) or not 1 <= len(scene_mapping) <= _MAX_SCENES:
        raise ValueError("scene_mapping must contain 1..40 scenes")

    scenes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in scene_mapping:
        if not isinstance(raw, dict):
            raise ValueError("each scene must be an object")
        sid = raw.get("scene_id")
        intent = raw.get("story_intent")
        if not isinstance(sid, str) or not _ID.fullmatch(sid) or sid in seen:
            raise ValueError("scene IDs must be valid and unique")
        if not isinstance(intent, str) or not intent.strip() or len(intent) > 2000:
            raise ValueError(f"scene {sid} requires a valid story_intent")
        feedback = raw.get("player_feedback", {})
        if not isinstance(feedback, dict):
            raise ValueError(f"scene {sid} player_feedback must be an object")
        visual = raw.get("visual_motif", feedback.get("visual", ""))
        music = raw.get("music_motif", feedback.get("audio", ""))
        if not isinstance(visual, str) or len(visual) > 1000:
            raise ValueError(f"scene {sid} has invalid visual_motif")
        if not isinstance(music, str) or len(music) > 1000:
            raise ValueError(f"scene {sid} has invalid music_motif")

        choices_raw = raw.get("choices", [])
        next_id = raw.get("next_scene_id")
        ending = raw.get("ending", False)
        if not isinstance(ending, bool):
            raise ValueError(f"scene {sid} ending must be boolean")
        if not isinstance(choices_raw, list) or len(choices_raw) > _MAX_CHOICES:
            raise ValueError(f"scene {sid} may contain at most 4 choices")
        modes = int(bool(choices_raw)) + int(next_id is not None) + int(ending)
        if modes != 1:
            raise ValueError(f"scene {sid} must define choices, next_scene_id, or ending=True")

        choices: list[dict[str, str]] = []
        choice_ids: set[str] = set()
        for choice in choices_raw:
            if not isinstance(choice, dict):
                raise ValueError(f"scene {sid} choices must be objects")
            cid, label, target = choice.get("choice_id"), choice.get("label"), choice.get("next_scene_id")
            if not isinstance(cid, str) or not _ID.fullmatch(cid) or cid in choice_ids:
                raise ValueError(f"scene {sid} choice IDs must be valid and unique")
            if not isinstance(label, str) or not label.strip() or len(label) > 120:
                raise ValueError(f"scene {sid} choice labels must contain 1..120 characters")
            if not isinstance(target, str) or not _ID.fullmatch(target):
                raise ValueError(f"scene {sid} choice target is invalid")
            choices.append({"choice_id": cid, "label": label.strip(), "next_scene_id": target})
            choice_ids.add(cid)

        if next_id is not None and (not isinstance(next_id, str) or not _ID.fullmatch(next_id)):
            raise ValueError(f"scene {sid} next_scene_id is invalid")
        scenes.append({
            "scene_id": sid,
            "story_intent": intent.strip(),
            "visual_motif": visual,
            "music_motif": music,
            "choices": choices,
            "next_scene_id": next_id,
            "ending": ending,
        })
        seen.add(sid)

    by_id = {scene["scene_id"]: scene for scene in scenes}
    entry = entry_scene_id or scenes[0]["scene_id"]
    if not isinstance(entry, str) or entry not in by_id:
        raise ValueError("entry_scene_id must reference a known scene")

    for scene in scenes:
        targets = [choice["next_scene_id"] for choice in scene["choices"]]
        if scene["next_scene_id"] is not None:
            targets.append(scene["next_scene_id"])
        if any(target not in by_id for target in targets):
            raise ValueError(f"scene {scene['scene_id']} references an unknown target")

    reachable: set[str] = set()
    pending = deque([entry])
    while pending:
        sid = pending.popleft()
        if sid in reachable:
            continue
        reachable.add(sid)
        scene = by_id[sid]
        pending.extend(choice["next_scene_id"] for choice in scene["choices"])
        if scene["next_scene_id"] is not None:
            pending.append(scene["next_scene_id"])
    unreachable = sorted(set(by_id) - reachable)
    if unreachable:
        raise ValueError("unreachable scenes: " + ", ".join(unreachable))

    return {
        "schema_version": "godot-story-graph.v1",
        "entry_scene_id": entry,
        "scenes": deepcopy(scenes),
        "scene_count": len(scenes),
        "max_choices_per_scene": _MAX_CHOICES,
    }


def resolve_story_transition(
    graph: object, current_scene_id: str, choice_id: str | None = None
) -> dict[str, Any]:
    """Return a read-only transition decision; never mutates the supplied graph."""
    if not isinstance(graph, dict) or graph.get("schema_version") != "godot-story-graph.v1":
        raise ValueError("graph must use godot-story-graph.v1")
    scenes = graph.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("graph scenes are invalid")
    current = next((item for item in scenes if isinstance(item, dict) and item.get("scene_id") == current_scene_id), None)
    if current is None:
        raise ValueError("current scene is not in the graph")
    choices = current.get("choices", [])
    if current.get("ending") is True:
        if choice_id is not None:
            raise ValueError("ending scenes do not accept choices")
        return {"status": "ENDING", "from_scene_id": current_scene_id, "next_scene_id": None}
    if current.get("next_scene_id") is not None:
        if choice_id is not None:
            raise ValueError("linear transitions do not accept choice IDs")
        return {
            "status": "ADVANCE",
            "from_scene_id": current_scene_id,
            "next_scene_id": current["next_scene_id"],
        }
    if not isinstance(choices, list) or not choices:
        raise ValueError("scene transition data is invalid")
    if choice_id is None:
        if len(choices) != 1:
            raise ValueError("choice_id is required when a scene has multiple choices")
        selected = choices[0]
    else:
        selected = next((item for item in choices if isinstance(item, dict) and item.get("choice_id") == choice_id), None)
        if selected is None:
            raise ValueError("choice_id is not available in the current scene")
    return {
        "status": "CHOICE_SELECTED",
        "from_scene_id": current_scene_id,
        "choice_id": selected["choice_id"],
        "next_scene_id": selected["next_scene_id"],
    }


__all__ = ["build_story_graph", "resolve_story_transition"]
