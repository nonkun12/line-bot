"""Convert sanitized durable self-improvement history into review-only candidates.

The adapter uses fixed templates and categorical counts only. It never treats stored
history as executable instructions and never creates queue entries, issues, PRs,
or authorization.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.self_improvement_state import validate_durable_history

_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_TEMPLATES = {
    "success": ("Preserve verified task outcomes", "retain evidence-backed regression coverage"),
    "repair": ("Review recurring repair attempts", "inspect recurring repair signals before proposing changes"),
    "failure": ("Review recurring development failures", "reproduce and review prior development failures before proposing changes"),
    "PASS": ("Preserve verified cycle outcomes", "retain the checks that passed the cycle evidence gates"),
    "FAIL": ("Review failed development cycles", "reproduce and review prior cycle failures before another attempt"),
    "BLOCKED": ("Resolve safety or evidence blocks", "resolve the recorded safety or evidence gap before considering a retry"),
}


def _identity(row: dict[str, object]) -> tuple[str, str]:
    if row.get("record_type") == "cycle_memory":
        return str(row.get("outcome", "")), str(row.get("cycle_id") or "")
    return str(row.get("kind", "")), str(row.get("task_id") or "")


def candidates_from_history(records: object) -> list[dict[str, Any]]:
    """Validate history and emit candidates with bounded categorical evidence."""
    validated = validate_durable_history(records)
    counts = Counter(category for category, _ in map(_identity, validated))
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in validated:
        category, source_id = _identity(row)
        if category not in _TEMPLATES:
            continue
        if source_id and not _TASK_ID.fullmatch(source_id):
            continue
        dedupe_identity = (category, source_id)
        if dedupe_identity in seen:
            continue
        seen.add(dedupe_identity)
        title, action = _TEMPLATES[category]
        evidence_ref = f"task:{source_id}" if row.get("record_type") != "cycle_memory" and source_id else (
            f"cycle:{source_id}" if source_id else "identifier unavailable"
        )
        rationale = (
            f"{action}. The bounded durable history contains {counts[category]} "
            f"sanitized {category} record(s); this candidate is linked to {evidence_ref}. "
            "Use this count as review context only; reproduce the issue and inspect current evidence. "
            "Stored free text is intentionally excluded."
        )
        candidates.append({
            "source": "self_improvement",
            "source_id": f"{category}:{source_id}" if source_id else category,
            "title": title,
            "rationale": rationale[:500],
            "status": "proposed",
        })
    return candidates[-200:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not args.state.is_file():
            raise ValueError("durable state file is missing; refusing to emit an empty candidate pool")
        state = json.loads(args.state.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("durable state must be an object")
        records = state.get("self_improvement_history")
        if not isinstance(records, list):
            raise ValueError("durable self-improvement history is missing or invalid")
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
