"""Build a bounded review queue for English core-image vocabulary.

This tool never promotes candidates into the runtime lexicon and never invents
word meanings or etymologies. It only emits review tasks for existing candidates
and reports the remaining gap to the configured target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_CANDIDATES = Path("agents/english/core_image_candidates.json")
DEFAULT_TARGET = 1000
_REQUIRED_FIELDS = ("word", "pronunciation", "core_image", "parts", "related", "example")
_WORD_RE = re.compile(r"^[a-z][a-z'-]{0,63}$")


def build_refill_plan(
    candidates: object,
    reviewed_words: set[str],
    *,
    limit: int = 4,
    target: int = DEFAULT_TARGET,
) -> dict[str, Any]:
    """Return a deterministic, bounded plan; do not mutate or approve any entry."""
    if type(limit) is not int or not 1 <= limit <= 4:
        raise ValueError("limit must be an integer from 1 through 4")
    if type(target) is not int or target < 1:
        raise ValueError("target must be a positive integer")
    if not isinstance(candidates, list):
        raise ValueError("candidate catalog must be a list")

    seen: set[str] = set()
    ready: list[dict[str, Any]] = []
    invalid_count = 0
    duplicate_count = 0
    for item in candidates:
        if not isinstance(item, dict):
            invalid_count += 1
            continue
        word = item.get("word")
        if not isinstance(word, str) or not _WORD_RE.fullmatch(word):
            invalid_count += 1
            continue
        if word in seen:
            duplicate_count += 1
            continue
        seen.add(word)
        if any(
            not isinstance(item.get(field), str) or not item[field].strip()
            for field in ("pronunciation", "core_image", "parts", "example")
        ) or not isinstance(item.get("related"), list):
            invalid_count += 1
            continue
        if word in reviewed_words:
            continue
        digest = hashlib.sha256(word.encode("utf-8")).hexdigest()[:12]
        ready.append({
            "task_id": f"english-core-image-review-{digest}",
            "word": word,
            "status": "PENDING_REVIEW",
            "requires_dictionary_source": True,
            "requires_etymology_verification": True,
            "candidate_data_present": True,
            "runtime_lexicon_mutation_authorized": False,
        })

    ready.sort(key=lambda task: task["word"])
    reviewed_count = len(reviewed_words)
    return {
        "schema_version": 1,
        "target_reviewed_words": target,
        "reviewed_words": reviewed_count,
        "reviewed_gap": max(0, target - reviewed_count),
        "candidate_words": len(seen),
        "candidate_pool_gap": max(0, target - len(seen)),
        "pending_review_candidates": len(ready),
        "invalid_candidates": invalid_count,
        "duplicate_candidates": duplicate_count,
        "tasks": ready[:limit],
        "truncated": len(ready) > limit,
        "auto_approval": False,
        "runtime_lexicon_mutation_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--target", type=int, default=DEFAULT_TARGET)
    args = parser.parse_args()
    try:
        candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
        from agents.english.core_image import _ENTRIES
        plan = build_refill_plan(candidates, set(_ENTRIES), limit=args.limit, target=args.target)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason_code": "catalog_invalid", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
    return 0 if plan["invalid_candidates"] == 0 and plan["duplicate_candidates"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
