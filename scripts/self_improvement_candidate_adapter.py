"""Convert sanitized durable self-improvement history into review-only candidates.

The adapter uses fixed templates only. It never treats stored history as executable
instructions and never creates queue entries, issues, PRs, or authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from scripts.self_improvement_state import validate_durable_history
from scripts.rea_self_improvement_history import validate_durable_rea_observations

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
    "rea_nonblocking_findings": (
        "Review non-blocking REA findings",
        "REA recorded non-blocking findings. Independently review the evidence and decide whether scanner coverage or regression checks should improve; this is not a developer failure.",
    ),
    "rea_finding_block": (
        "Review REA high-severity evidence",
        "REA blocked a task because of high- or critical-severity evidence. Independently inspect the security/evidence finding; do not treat it as a developer task failure or authorize execution.",
    ),
    "rea_evidence_block": (
        "Improve REA evidence completeness",
        "REA could not establish complete, SHA-bound evidence. Review scanner availability and evidence integrity; this is not a developer task failure.",
    ),
}


def candidates_from_history(records: object, rea_observations: object = None) -> list[dict[str, Any]]:
    """Validate task history and separate REA observations into fixed review candidates."""
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

    # REA security/evidence outcomes remain a distinct signal family. They are
    # never converted into task failures, queue entries, or execution authority.
    validated_rea = validate_durable_rea_observations(
        [] if rea_observations is None else rea_observations
    )
    rea_templates = {
        "nonblocking_findings": "rea_nonblocking_findings",
        "finding_block": "rea_finding_block",
        "evidence_block": "rea_evidence_block",
    }
    for row in validated_rea:
        template_key = rea_templates.get(row["category"])
        if template_key is None:
            continue
        title, rationale = _TEMPLATES[template_key]
        task_digest = hashlib.sha256(row["task_id"].encode("utf-8")).hexdigest()[:10]
        source_id = f"rea-observation:{row['category']}:{row['cycle_id']}:{task_digest}"
        identity = (template_key, source_id)
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append({
            "source": "self_improvement",
            "source_id": source_id,
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
        if not args.state.is_file():
            raise ValueError("durable state file is missing; refusing to emit an empty candidate pool")
        state = json.loads(args.state.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("durable state must be an object")
        records = state.get("self_improvement_history")
        if not isinstance(records, list):
            raise ValueError("durable self-improvement history is missing or invalid")
        rea_observations = state.get("rea_observations", [])
        rows = candidates_from_history(records, rea_observations)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"self-improvement candidate adapter stopped safely: {exc}")
        return 2
    print(f"SELF_IMPROVEMENT_REVIEW_CANDIDATES={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
