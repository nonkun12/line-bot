"""Canonical machine-readable failure codes and triage categories."""
from __future__ import annotations

import re

# One source of truth for extraction, Recovery AI, and Maintenance AI.
FAILURE_CODE_CATEGORIES = {
    "append_only_test_anchor_or_size_invalid": "invalid_task",
    "anchor_count": "invalid_task",
    "change_outside_selected_file": "security_violation",
    "deterministic_anchor_not_unique": "invalid_task",
    "deterministic_plan_invalid": "invalid_task",
    "deterministic_plan_too_large": "invalid_task",
    "deterministic_target_mismatch": "invalid_task",
    "existing_test_modified": "security_violation",
    "existing_test_modified_repair_failed": "security_violation",
    "invalid_change_count": "invalid_task",
    "invalid_change_count_repair_failed": "invalid_task",
    "invalid_failure_code_evidence": "invalid_evidence",
    "nonce_mismatch": "security_violation",
    "outside_allowed_paths": "security_violation",
    "protected_file": "security_violation",
    "sha_mismatch": "security_violation",
}
SAFE_FAILURE_CODES = frozenset(FAILURE_CODE_CATEGORIES)


def extract_safe_failure_code(value: object) -> str | None:
    """Extract a known code, including bounded dynamic diagnostic suffixes."""
    if not isinstance(value, str) or not value:
        return None
    for code in sorted(SAFE_FAILURE_CODES, key=len, reverse=True):
        if code == "anchor_count":
            if re.search(r"(?<![A-Za-z0-9_])anchor_count_[A-Za-z0-9_./-]+", value):
                return code
        elif re.search(rf"(?<![A-Za-z0-9_]){re.escape(code)}(?![A-Za-z0-9_])", value):
            return code
    return None


def is_safe_failure_code(value: object) -> bool:
    return isinstance(value, str) and value in SAFE_FAILURE_CODES


def failure_code_category(value: object) -> str | None:
    if not is_safe_failure_code(value):
        return None
    return FAILURE_CODE_CATEGORIES[value]


__all__ = [
    "FAILURE_CODE_CATEGORIES",
    "SAFE_FAILURE_CODES",
    "extract_safe_failure_code",
    "failure_code_category",
    "is_safe_failure_code",
]
