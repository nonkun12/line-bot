# Godot prototype generator

Generate a new Godot 4 project from a human-approved design JSON:

    python scripts/generate_godot_prototype.py --design approved-godot-design.json --output ./godot-story-prototype

The output path must not exist and its parent must already exist. The generated
project contains text files only. Open it in Godot 4.x and press F5. The first
playable loop advances through approved story scenes and emits scene-linked
audio cue signals. Actual music playback and visual asset integration remain
separate human-reviewed steps. No media is invented, copied, or published.
