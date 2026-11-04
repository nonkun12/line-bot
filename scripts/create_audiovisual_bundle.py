"""CLI for creating a local original music + video production bundle.

Example:
  python -m scripts.create_audiovisual_bundle scenario.json ./output/film-01
  python -m scripts.create_audiovisual_bundle scenario.json ./output/film-01 --scene-media-json scene-assets.json --audio-path music.wav

No external services or downloads are used.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from agents.media.production import create_audiovisual_production_bundle


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create an original audiovisual production bundle.")
    parser.add_argument("scenario_json", type=Path, help="validated video-scenario.v1 JSON")
    parser.add_argument("output_dir", type=Path, help="new output directory; existing directories are rejected")
    parser.add_argument("--bpm", type=int, default=120)
    parser.add_argument("--soundfont", type=Path, help="optional local SF2/SF3 soundfont for FluidSynth")
    parser.add_argument("--audio-path", type=Path, help="optional full-length local WAV for video assembly")
    parser.add_argument("--scene-media-json", type=Path, help="JSON object mapping scene IDs to local clip/image paths")
    args = parser.parse_args(argv)

    try:
        scenario = json.loads(args.scenario_json.read_text(encoding="utf-8"))
        scene_media = None
        if args.scene_media_json is not None:
            scene_media = json.loads(args.scene_media_json.read_text(encoding="utf-8"))
            if not isinstance(scene_media, dict):
                raise ValueError("scene-media JSON must be an object mapping scene IDs to paths")
        result = create_audiovisual_production_bundle(
            scenario,
            args.output_dir,
            bpm=args.bpm,
            soundfont_path=args.soundfont,
            scene_media=scene_media,
            audio_path=args.audio_path,
        )
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
