"""Convert sanitized durable self-improvement history into review-only candidates.

The adapter uses fixed templates only. It never treats stored history as executable
instructions and never creates queue entries, issues, PRs, or authorization.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from scripts.self_improvement_state import validate_durable_history

_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_TEMPLATES = {
    "success": (
        "Preserve verified task outcomes",
        "A verified task outcome was recorded; retain evidence-backed regression coverage.",
    ),
    "repair": (
        "Review recurring repair attempts",
        "A repair signal was recorded; inspect recurring causes before proposing changes.",
    ),
    "failure": (
        "Review recurring development failures",
        "A development failure signal was recorded; inspect evidence before proposing changes.",
    ),
    "PASS": (
        "Preserve verified cycle outcomes",
        "A cycle passed its evidence gates; retain the verified checks and regression coverage.",
    ),
    "FAIL": (
        "Review failed development cycles",
        "A cycle failure was recorded; review the failure evidence before another attempt.",
    ),
    "BLOCKED": (
        "Resolve safety or evidence blocks",
        "A cycle was blocked; resolve the safety or evidence gap before considering a retry.",
    ),
}


def candidates_from_history(records: object) -> list[dict[str, Any]]:
    """Validate history and emit fixed, bounded candidate records."""
    validated = validate_durable_history(records)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in validated:
        if row.get("record_type") == "cycle_memory":
            category = row.get("outcome")
            source_id = row.get("cycle_id", "")
        else:
            category = row.get("kind")
            source_id = row.get("task_id") or ""
        if not isinstance(category, str) or category not in _TEMPLATES:
            continue
        if source_id and (not isinstance(source_id, str) or not _TASK_ID.fullmatch(source_id)):
            continue
        title, rationale = _TEMPLATES[category]
        dedupe_identity = (category, source_id)
        if dedupe_identity in seen:
            continue
        seen.add(dedupe_identity)
        candidates.append({
            "source": "self_improvement",
            "source_id": f"{category}:{source_id}" if source_id else category,
            "title": title,
            "rationale": rationale,
            "status": "proposed",
        })
    return candidates[-200:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.state.exists():
            state = json.loads(args.state.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("durable state must be an object")
            records = state.get("self_improvement_history", [])
        else:
            records = []
        rows = candidates_from_history(records)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"self-improvement candidate adapter stopped safely: {exc}")
        return 2
    print(f"SELF_IMPROVEMENT_REVIEW_CANDIDATES={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
