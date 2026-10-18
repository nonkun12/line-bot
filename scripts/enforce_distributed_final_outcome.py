"""Fail-closed final outcome gate for the distributed autonomous loop."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_SUCCESS_OUTCOMES = frozenset({"COMPLETED", "NOT_RUN"})


def validate_final_outcome(payload: object) -> tuple[bool, str]:
    """Validate machine-readable final outcome; unknown or malformed data blocks."""
    if not isinstance(payload, dict):
        return False, "invalid_payload"
    if payload.get("schema_version") != 1 or isinstance(payload.get("schema_version"), bool):
        return False, "invalid_schema_version"
    outcome = payload.get("outcome")
    if not isinstance(outcome, str) or outcome not in {
        "COMPLETED", "NOT_RUN", "BLOCKED", "FAILED", "INCOMPLETE"
    }:
        return False, "unknown_or_missing_outcome"
    if outcome not in _SUCCESS_OUTCOMES:
        return False, f"outcome_{outcome.lower()}"
    return True, outcome


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    path = Path(args.input)
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("::error::Final machine-readable outcome is missing or invalid; failing closed.")
        return 1
    allowed, reason = validate_final_outcome(payload)
    if not allowed:
        print(f"::error::Distributed-loop final outcome rejected: {reason}")
        return 1
    print(f"Final distributed-loop outcome accepted: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
