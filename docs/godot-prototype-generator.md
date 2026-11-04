# Godot prototype generator

Generate a new Godot 4 project from a human-approved design JSON:

    python scripts/generate_godot_prototype.py --design approved-godot-design.json --output ./godot-story-prototype

To connect local assets, prepare a manifest and pass `--asset-manifest`:

    python scripts/generate_godot_prototype.py --design approved-godot-design.json --asset-manifest approved-assets.json --output ./godot-story-prototype

Manifest format:

    {
      "schema_version": "godot-approved-assets.v1",
      "human_approved": true,
      "publication_authorized": false,
      "scenes": [{
        "scene_id": "opening",
        "approval_note": "Reviewed original local asset",
        "audio_path": "res://assets/opening.ogg",
        "image_path": "res://assets/opening.png",
        "video_path": "res://assets/opening.ogv"
      }]
    }

Supported media: audio WAV/OGG/MP3, still images PNG/JPG/JPEG/WEBP,
and Ogg Theora video OGV. Put those files manually under the generated
project's `assets/` folder. The generator does not copy, download, edit,
or create media. A missing referenced asset is skipped with a warning.

The manifest requires explicit human approval, a note for each scene, and
project-local paths. Existing output directories are never overwritten.
Open the generated project in Godot 4.x and press F5. Scene transitions
start the corresponding approved audio and visual assets together.
