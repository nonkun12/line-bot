"""CLI for creating a new Godot project from approved design JSON."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from agents.media.godot_prototype_generator import generate_godot_project

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", required=True)
    parser.add_argument("--output", required=True, help="new project directory; must not exist")
    args = parser.parse_args()
    try:
        design = json.loads(Path(args.design).read_text(encoding="utf-8"))
        result = generate_godot_project(design, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
