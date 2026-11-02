"""Allowlisted machine-readable failure codes for autonomous-loop triage."""
from __future__ import annotations

import re

SAFE_FAILURE_CODES = frozenset({
    "existing_test_modified_repair_failed",
    "invalid_change_count_repair_failed",
    "append_only_test_anchor_or_size_invalid",
})


def extract_safe_failure_code(value: object) -> str | None:
    """Extract one known code from diagnostic text; never return arbitrary text."""
    if not isinstance(value, str) or not value:
        return None
    for code in sorted(SAFE_FAILURE_CODES):
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(code)}(?![A-Za-z0-9_])", value):
            return code
    return None


def is_safe_failure_code(value: object) -> bool:
    return isinstance(value, str) and value in SAFE_FAILURE_CODES


__all__ = ["SAFE_FAILURE_CODES", "extract_safe_failure_code", "is_safe_failure_code"]
