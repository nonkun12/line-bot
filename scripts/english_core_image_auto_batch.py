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
    if "語源を断定" not in entry["parts"] and "語源の細かな分解は断定せず" not in entry["parts"]:
        # A semantic mnemonic is fine; avoid claiming unverified word history.
        if not any(token in entry["parts"] for token in ("語源の", "語源分解", "意味の", "語源の細", "形に注意", "の形に", "動詞では", "通常は", "名詞では", "通常 avoid", "既存語")):
            raise ValueError(f"{word}: parts needs conservative usage/source note")


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
    if args.batch_size < 1 or args.batch_size > 100:
        parser.error("--batch-size must be between 1 and 100")

    source = MODULE.read_text(encoding="utf-8")
    existing, dict_end_line = load_existing(source)
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    if not isinstance(queue, list):
        raise ValueError("candidate queue must be a JSON array")

    seen_queue: set[str] = set()
    selected = []
    for entry in queue:
        if not isinstance(entry, dict):
            raise ValueError("every candidate must be an object")
        validate_entry(entry)
        word = entry["word"]
        if word in seen_queue:
            raise ValueError(f"duplicate candidate in queue: {word}")
        seen_queue.add(word)
        if word not in existing:
            selected.append(entry)
        if len(selected) >= args.batch_size:
            break

    if not selected:
        print("NO_CHANGE: no new reviewed candidates remain")
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
