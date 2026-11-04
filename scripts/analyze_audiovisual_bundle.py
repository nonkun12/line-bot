"""Run bounded local WAV/video signal analysis for an authored scenario."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

# Allow direct execution as: python scripts/analyze_audiovisual_bundle.py ...
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agents.media.signal_analysis import analyze_audiovisual_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only, bounded analysis of a local scenario, WAV, and video draft."
    )
    parser.add_argument("--scenario", required=True, type=Path, help="video-scenario.v1 JSON")
    parser.add_argument("--audio", required=True, type=Path, help="PCM16 WAV draft (max 90 seconds)")
    parser.add_argument("--video", required=True, type=Path, help="MP4/MOV/MKV/WebM draft")
    parser.add_argument("--output", type=Path, help="Optional JSON report path; stdout when omitted")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with args.scenario.open("r", encoding="utf-8") as handle:
            scenario = json.load(handle)
        report = analyze_audiovisual_bundle(
            scenario, args.audio, args.video
        )
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"analysis failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
