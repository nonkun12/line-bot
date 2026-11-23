"""Fail-closed policy for bounded distributed-loop self-healing.

This module classifies evidence only. It never edits files, clears HOLD, dispatches
workflows, merges, or deploys. A separate trusted executor must enforce the action.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from typing import Any


SAFE_TRANSIENT_CODES = frozenset({
    "provider_rate_limited",
    "provider_service_unavailable",
    "provider_network_transient",
})
SAFE_REPAIR_CATEGORIES = frozenset({
    "test_regression",
    "timeout",
    "process_crash",
})
MAX_FAILURES = 3
MAX_REPAIR_ATTEMPTS = 1


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    task_id: str = ""
    fingerprint: str = ""
    requires_rea: bool = False
    requires_human: bool = False


def _sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def decide(evidence: dict[str, Any]) -> Decision:
    """Return one bounded action from a sanitized, structured failure record."""
    if not isinstance(evidence, dict):
        return Decision("HOLD", "invalid_evidence", requires_human=True)

    task_id = evidence.get("task_id", "")
    fingerprint = evidence.get("fingerprint", "")
    category = evidence.get("category", "")
    failures = evidence.get("consecutive_failures", 0)
    attempts = evidence.get("same_fingerprint_attempts", 0)
    held = evidence.get("held")
    base_sha = evidence.get("base_sha")
    produced_sha = evidence.get("produced_sha")
    rea_status = evidence.get("rea_status")

    if (
        not isinstance(task_id, str) or not task_id
        or len(task_id) > 100
        or not re.fullmatch(r"[A-Za-z0-9._-]+", task_id)
        or not isinstance(fingerprint, str)
        or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
        or type(failures) is not int or failures < 0
        or type(attempts) is not int or attempts < 0
        or type(held) is not bool
    ):
        return Decision("HOLD", "invalid_or_incomplete_failure_identity", requires_human=True)

    if held:
        return Decision("HOLD", "task_already_held", task_id, fingerprint, requires_human=True)
    if failures >= MAX_FAILURES:
        return Decision("HOLD", "failure_budget_exhausted", task_id, fingerprint, requires_human=True)

    if category == "transient":
        code = evidence.get("failure_code")
        retry_count = evidence.get("retry_count", 0)
        if (
            isinstance(code, str) and code in SAFE_TRANSIENT_CODES
            and _sha(base_sha) and base_sha == produced_sha
            and evidence.get("working_tree_clean") is True
            and type(retry_count) is int and 0 <= retry_count < 2
        ):
            return Decision("RETRY_TRANSIENT", "allowlisted_transient_failure", task_id, fingerprint)
        return Decision("HOLD", "transient_retry_not_proven_safe", task_id, fingerprint, requires_human=True)

    if category in SAFE_REPAIR_CATEGORIES:
        allowed_paths = evidence.get("allowed_paths")

        def safe_repo_path(path: Any) -> bool:
            if not isinstance(path, str) or not path or len(path) > 240:
                return False
            # Exact repository-relative POSIX paths only.
            if path.startswith("/") or chr(92) in path or ":" in path:
                return False
            parts = path.split("/")
            if any(part in {"", ".", ".."} for part in parts):
                return False
            if any(char in part for part in parts for char in "*?[]{}"):
                return False
            return True

        if (
            attempts < MAX_REPAIR_ATTEMPTS
            and isinstance(allowed_paths, list) and bool(allowed_paths)
            and len(allowed_paths) <= 20
            and all(safe_repo_path(path) for path in allowed_paths)
            and len(set(allowed_paths)) == len(allowed_paths)
            and evidence.get("execution_authorized") is True
            and rea_status == "PRE_REPAIR_PASS"
        ):
            return Decision(
                "REPAIR_ONCE", "bounded_repair_budget_available", task_id,
                fingerprint, requires_rea=True,
            )
        return Decision("HOLD", "repair_preconditions_not_met", task_id, fingerprint, requires_human=True)

    return Decision("HOLD", "unknown_or_nonrepairable_failure", task_id, fingerprint, requires_human=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        with open(args.input, encoding="utf-8") as stream:
            evidence = json.load(stream)
        decision = decide(evidence)
    except (OSError, UnicodeError, json.JSONDecodeError):
        decision = Decision("HOLD", "evidence_unreadable", requires_human=True)
    print(json.dumps(asdict(decision), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
