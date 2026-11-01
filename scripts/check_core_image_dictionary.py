#!/usr/bin/env python3
"""Offline quality gate for the reviewed English core-image dictionary.

This tool never invents definitions or edits the dictionary. It reports the
verified entry count and fails on malformed or duplicate entries so that
unreviewed placeholders cannot be mistaken for progress toward 1,000 words.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DICTIONARY = ROOT / "agents" / "english" / "core_image.py"
REQUIRED_FIELDS = ("word", "pronunciation", "core_image", "parts", "related", "example")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=1000)
    args = parser.parse_args()
    source = DICTIONARY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DICTIONARY))

    entries_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "_ENTRIES":
            entries_node = node.value
            break
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_ENTRIES" for t in node.targets):
            entries_node = node.value
            break
    if not isinstance(entries_node, ast.Dict):
        print("FAIL: could not locate literal _ENTRIES dictionary", file=sys.stderr)
        return 2

    words: list[str] = []
    errors: list[str] = []
    for key_node, value_node in zip(entries_node.keys, entries_node.values):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            errors.append("dictionary key is not a literal string")
            continue
        word = key_node.value
        words.append(word)
        if not re.fullmatch(r"[a-z][a-z'-]{0,63}", word):
            errors.append(f"invalid word key: {word!r}")
        if not isinstance(value_node, ast.Call) or not (
            isinstance(value_node.func, ast.Name) and value_node.func.id == "WordEntry"
        ):
            errors.append(f"{word}: value is not a WordEntry")
            continue
        fields = {kw.arg: kw.value for kw in value_node.keywords if kw.arg}
        missing = [field for field in REQUIRED_FIELDS if field not in fields]
        if missing:
            errors.append(f"{word}: missing fields {', '.join(missing)}")
        entry_word = fields.get("word")
        if not isinstance(entry_word, ast.Constant) or entry_word.value != word:
            errors.append(f"{word}: WordEntry.word must match its dictionary key")
        for field in ("pronunciation", "core_image", "parts", "example"):
            value = fields.get(field)
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or not value.value.strip():
                errors.append(f"{word}: {field} must be a non-empty literal string")
        related = fields.get("related")
        if not isinstance(related, (ast.Tuple, ast.List)) or not related.elts:
            errors.append(f"{word}: related must be a non-empty tuple/list")

    duplicates = sorted({word for word in words if words.count(word) > 1})
    if duplicates:
        errors.append("duplicate keys: " + ", ".join(duplicates))

    count = len(words)
    print(f"Reviewed dictionary entries: {count}/{args.target}")
    print(f"Remaining to target: {max(0, args.target - count)}")
    if errors:
        print("Validation errors:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Quality gate: PASS (structure only; semantic review is still required)")
    if count < args.target:
        print("Target status: IN_PROGRESS (no placeholder entries were generated)")
    else:
        print("Target status: TARGET_REACHED; run semantic review and full tests before release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
