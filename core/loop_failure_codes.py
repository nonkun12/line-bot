"""Canonical machine-readable failure codes and triage categories."""
from __future__ import annotations

import re

# One source of truth for extraction, Recovery AI, and Maintenance AI.
FAILURE_CODE_CATEGORIES = {
    "append_only_test_anchor_or_size_invalid": "invalid_task",
    "anchor_count": "invalid_task",
    "change_outside_selected_file": "security_violation",
    "change_path_outside_root": "security_violation",
    "deterministic_anchor_not_unique": "invalid_task",
    "deterministic_plan_invalid": "invalid_task",
    "deterministic_plan_too_large": "invalid_task",
    "deterministic_target_mismatch": "invalid_task",
    "deterministic_target_unavailable_or_disallowed": "invalid_task",
    "duplicate_change_path": "invalid_task",
    "existing_test_missing": "invalid_task",
    "existing_test_modified": "security_violation",
    "existing_test_modified_repair_failed": "security_violation",
    "invalid_change": "invalid_task",
    "invalid_change_count": "invalid_task",
    "invalid_change_count_repair_failed": "invalid_task",
    "invalid_failure_code_evidence": "invalid_evidence",
    "invalid_task": "invalid_task",
    "invalid_old_new": "invalid_task",
    "invalid_plan": "invalid_task",
    "no_op_change": "invalid_task",
    "diff_marker_in_replacement": "invalid_task",
    "change_too_large": "invalid_task",
    "change_target_unreadable": "invalid_task",
    "manager_could_not_select_safe_target": "invalid_task",
    "manager_selection_missing": "invalid_task",
    "nonce_mismatch": "security_violation",
    "operational_validation_anchor_not_unique": "invalid_task",
    "operational_validation_failure": "invalid_task",
    "operational_validation_plan_invalid": "invalid_task",
    "operational_validation_plan_too_large": "invalid_task",
    "outside_allowed_paths": "security_violation",
    "protected_file": "security_violation",
    "provider_rate_limited": "rate_limited",
    "provider_service_unavailable": "service_unavailable",
    "provider_network_transient": "network_transient",
    "required_regression_test_missing": "invalid_task",
    "self_improvement_policy": "security_violation",
    "sha_mismatch": "security_violation",
}
SAFE_FAILURE_CODES = frozenset(FAILURE_CODE_CATEGORIES)
_CATEGORY_SEVERITY = {
    "security_violation": 3,
    "invalid_evidence": 2,
    "invalid_task": 1,
}

# Prefix aliases normalize human-readable diagnostics emitted by legacy stages.
_FAILURE_PATTERNS = (
    (re.compile(r"(?<![A-Za-z0-9_])change_path_outside_root(?![A-Za-z0-9_])"), "change_path_outside_root"),
    (re.compile(r"(?<![A-Za-z0-9_])self_improvement_policy(?=[:\s]|$)"), "self_improvement_policy"),
    (re.compile(r"(?<![A-Za-z0-9_])required_regression_test_missing[A-Za-z0-9_./:-]*"), "required_regression_test_missing"),
    (re.compile(r"(?<![A-Za-z0-9_])existing_test_missing(?=[:\s]|$)"), "existing_test_missing"),
    (re.compile(r"(?<![A-Za-z0-9_])operational_validation_anchor_not_unique"), "operational_validation_anchor_not_unique"),
    (re.compile(r"(?<![A-Za-z0-9_])operational_validation_[A-Za-z0-9_./:-]+"), "operational_validation_failure"),
    (re.compile(r"(?<![A-Za-z0-9_])operational_validation_plan_invalid"), "operational_validation_plan_invalid"),
    (re.compile(r"(?<![A-Za-z0-9_])operational_validation_plan_too_large"), "operational_validation_plan_too_large"),
    (re.compile(r"deterministic target unavailable or disallowed"), "deterministic_target_unavailable_or_disallowed"),
    (re.compile(r"deterministic target mismatch"), "deterministic_target_mismatch"),
    (re.compile(r"manager could not select a safe target"), "manager_could_not_select_safe_target"),
    (re.compile(r"manager selection missing"), "manager_selection_missing"),
    (re.compile(r"(?<![A-Za-z0-9_])invalid_change(?![A-Za-z0-9_])"), "invalid_change"),
    (re.compile(r"(?<![A-Za-z0-9_])invalid_old_new(?![A-Za-z0-9_])"), "invalid_old_new"),
    (re.compile(r"(?<![A-Za-z0-9_])no_op_change(?![A-Za-z0-9_])"), "no_op_change"),
    (re.compile(r"(?<![A-Za-z0-9_])diff_marker_in_replacement(?![A-Za-z0-9_])"), "diff_marker_in_replacement"),
    (re.compile(r"(?<![A-Za-z0-9_])change_too_large(?![A-Za-z0-9_])"), "change_too_large"),
    (re.compile(r"(?<![A-Za-z0-9_])invalid_plan(?![A-Za-z0-9_])"), "invalid_plan"),
    (re.compile(r"(?<![A-Za-z0-9_])duplicate_change_path(?![A-Za-z0-9_])"), "duplicate_change_path"),
    (re.compile(r"(?<![A-Za-z0-9_])change_target_unreadable(?![A-Za-z0-9_])"), "change_target_unreadable"),
)

def extract_safe_failure_code(value: object) -> str | None:
    """Extract a canonical code; security evidence wins deterministically."""
    if not isinstance(value, str) or not value:
        return None
    matches: set[str] = set()
    # Only explicit, bounded provider status/transport signals are transient.
    # HTTP 400/401/403 and unknown errors remain non-transient and fail closed.
    statuses = [int(item) for item in re.findall(r"\bstatus\s*=\s*(\d{3})\b", value, re.IGNORECASE)]
    if 429 in statuses:
        matches.add("provider_rate_limited")
    elif any(status in {408, 425} or 500 <= status <= 599 for status in statuses):
        matches.add("provider_service_unavailable")
    elif re.search(r"\b(?:APITimeoutError|APIConnectionError|TimeoutError|ConnectionError)\b", value):
        matches.add("provider_network_transient")
    for pattern, code in _FAILURE_PATTERNS:
        if pattern.search(value):
            matches.add(code)
    for code in SAFE_FAILURE_CODES:
        if code == "anchor_count":
            if re.search(r"(?<![A-Za-z0-9_])anchor_count_[A-Za-z0-9_./-]+", value):
                matches.add(code)
        elif re.search(rf"(?<![A-Za-z0-9_]){re.escape(code)}(?![A-Za-z0-9_])", value):
            matches.add(code)
    if not matches:
        return None
    return min(
        matches,
        key=lambda code: (
            -_CATEGORY_SEVERITY[FAILURE_CODE_CATEGORIES[code]],
            -len(code),
            code,
        ),
    )

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
