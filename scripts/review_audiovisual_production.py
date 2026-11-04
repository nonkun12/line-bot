"""Run integrated audiovisual review and optionally export Creator suggestions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agents.media.creator_feedback import build_creator_feedback_candidates
from agents.media.integrated_audiovisual_review import review_audiovisual_production


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only audiovisual Creator-Critic with optional feedback proposals."
    )
    parser.add_argument("--scenario", required=True, type=Path, help="video-scenario.v1 JSON")
    parser.add_argument("--music-plan", required=True, type=Path, help="video-music-plan.v1 JSON")
    parser.add_argument("--edl", required=True, type=Path, help="audiovisual-edl.v1 JSON")
    parser.add_argument("--storyboard", required=True, type=Path, help="video-storyboard.v1 JSON")
    parser.add_argument("--signal-report", required=True, type=Path, help="audiovisual-bundle-signal-report.v1 JSON")
    parser.add_argument("--output", type=Path, help="Optional review report path; stdout when omitted")
    parser.add_argument(
        "--feedback-output", type=Path,
        help="Optional path for evidence-linked Creator suggestions; proposals only",
    )
    return parser


def _read_json(path: Path, label: str) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON root must be an object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = review_audiovisual_production(
            _read_json(args.scenario, "scenario"),
            _read_json(args.music_plan, "music plan"),
            _read_json(args.edl, "EDL"),
            _read_json(args.storyboard, "storyboard"),
            _read_json(args.signal_report, "signal report"),
        )
        if args.feedback_output:
            feedback = build_creator_feedback_candidates(report)
            args.feedback_output.write_text(
                json.dumps(feedback, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"integrated review failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
