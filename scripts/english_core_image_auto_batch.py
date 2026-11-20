#!/usr/bin/env python3
"""Add the next reviewed local vocabulary batch to core_image.py.

No network/API calls, no guessed etymologies, and no automatic merge/deploy.
The scheduled workflow opens or updates a PR for human review.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "agents/english/core_image.py"
QUEUE = ROOT / "agents/english/core_image_candidates.json"
REGISTRY = ROOT / "agents/english/vocabulary_registry.json"
WORD_RE = re.compile(r"^[a-z][a-z'-]{0,63}$")
REQUIRED = ("word", "pronunciation", "core_image", "parts", "related", "example")


def load_existing(source: str) -> tuple[set[str], int]:
    tree = ast.parse(source)
    node = next(
        n for n in tree.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "_ENTRIES"
        or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_ENTRIES" for t in n.targets)
    )
    keys = set()
    for item in ast.walk(node.value):
        if isinstance(item, ast.Dict):
            for key in item.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
            break
    return keys, node.end_lineno



def load_registry(path: Path, existing: set[str]) -> set[str]:
    """Load the duplicate registry and fail closed if it is stale or inconsistent."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"vocabulary registry is required and must be valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("unsupported or missing vocabulary registry schema")

    def words(key: str) -> set[str]:
        value = data.get(key)
        if not isinstance(value, list):
            raise ValueError(f"registry {key} must be a list")
        result: set[str] = set()
        for word in value:
            if not isinstance(word, str) or not WORD_RE.fullmatch(word) or word != word.strip().lower():
                raise ValueError(f"registry {key} contains an invalid normalized headword")
            if word in result:
                raise ValueError(f"registry {key} contains duplicate headword: {word}")
            result.add(word)
        return result

    current = words("current_headwords")
    historical = words("historical_seen_headwords")
    reserved = words("reserved_candidate_headwords")
    flashcards = words("reserved_flashcard_headwords")
    blocked = words("blocked_headwords")
    if current != existing:
        raise ValueError("registry current_headwords do not match the canonical dictionary")
    expected = current | historical | reserved | flashcards
    if blocked != expected:
        raise ValueError("registry blocked_headwords must equal the union of all registry sets")

    scope = data.get("source_scope")
    canonical = scope.get("canonical_dictionary") if isinstance(scope, dict) else None
    if not isinstance(canonical, dict) or canonical.get("headword_count") != len(current):
        raise ValueError("registry canonical dictionary source/count is missing or stale")
    counts = data.get("counts")
    expected_counts = {
        "current": len(current),
        "historical": len(historical),
        "reserved_candidates": len(reserved),
        "reserved_flashcard_verbs": len(flashcards),
        "blocked_unique": len(blocked),
    }
    if counts != expected_counts:
        raise ValueError("registry counts do not match the verified headword sets")
    return blocked

def validate_entry(entry: dict) -> None:
    missing = [key for key in REQUIRED if key not in entry]
    if missing:
        raise ValueError(f"candidate missing fields: {missing}")
    word = entry["word"]
    if not isinstance(word, str) or not WORD_RE.fullmatch(word):
        raise ValueError(f"invalid word key: {word!r}")
    for key in ("pronunciation", "core_image", "parts", "example"):
        if not isinstance(entry[key], str) or not entry[key].strip():
            raise ValueError(f"{word}: {key} must be non-empty text")
    related = entry["related"]
    if not isinstance(related, list) or len(related) < 2 or not all(isinstance(x, str) and x.strip() for x in related):
        raise ValueError(f"{word}: related must contain at least two non-empty strings")

def render(entry: dict) -> str:
    fields = [
        f"word={entry['word']!r}",
        f"pronunciation={entry['pronunciation']!r}",
        f"core_image={entry['core_image']!r}",
        f"parts={entry['parts']!r}",
        f"related={tuple(entry['related'])!r}",
        f"example={entry['example']!r}",
    ]
    if entry.get("note"):
        fields.append(f"note={entry['note']!r}")
    return f"    {entry['word']!r}: WordEntry(" + ", ".join(fields) + "),"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 25:
        parser.error("--batch-size must be between 1 and 25")

    source = MODULE.read_text(encoding="utf-8")
    existing, dict_end_line = load_existing(source)
    blocked = load_registry(REGISTRY, existing)
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    if not isinstance(queue, list):
        raise ValueError("candidate queue must be a JSON array")

    # Validate the entire queue before selecting a batch. This catches duplicates
    # and malformed entries even when they occur after the batch-size boundary.
    seen_queue: set[str] = set()
    eligible = []
    blocked_candidates = []
    for entry in queue:
        if not isinstance(entry, dict):
            raise ValueError("every candidate must be an object")
        validate_entry(entry)
        word = entry["word"]
        if word in seen_queue:
            raise ValueError(f"duplicate candidate in queue: {word}")
        seen_queue.add(word)
        if word in blocked:
            blocked_candidates.append(word)
        else:
            eligible.append(entry)

    print(f"DICTIONARY_COUNT={len(existing)}")
    print(f"REGISTRY_BLOCKED_COUNT={len(blocked)}")
    print(f"REGISTRY_BLOCKED_CANDIDATES={len(blocked_candidates)}")
    print(f"CANDIDATE_QUEUE_COUNT={len(queue)}")
    print(f"ELIGIBLE_CANDIDATES={len(eligible)}")
    print(f"TARGET_REMAINING={max(0, 1000 - len(existing))}")
    selected = eligible[:args.batch_size]

    if not selected:
        print("NO_CHANGE: queue_exhausted_no_new_reviewed_candidates")
        return 0

    lines = source.splitlines()
    insert_at = dict_end_line - 1  # immediately before the dictionary's closing brace
    rendered = [render(entry) for entry in selected]
    lines[insert_at:insert_at] = rendered
    updated = "\n".join(lines) + ("\n" if source.endswith("\n") else "")
    ast.parse(updated)
    MODULE.write_text(updated, encoding="utf-8")
    print(f"Added {len(selected)} reviewed candidates: {', '.join(x['word'] for x in selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
