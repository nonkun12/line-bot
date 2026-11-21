"""Attach catalog exhaustion findings to the human-review report only.

This script only annotates the proposal report. It never edits the runtime queue,
registered task catalog, durable state, GitHub issues, or execution permissions.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

MAX_CANDIDATES = 4
ID_RE = re.compile(r"^review-coverage-gap-[a-f0-9]{10}$")
FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")
FUNCTION_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
TARGETS = {
    "tests/test_line_development_runtime.py": "core/line_development_runtime.py",
    "tests/test_agent_runtime.py": "core/agent_runtime.py",
    "tests/test_management_router.py": "core/management_router.py",
    "tests/test_control_tower_orchestrator.py": "core/control_tower_orchestrator.py",
    "tests/test_recovery_ai.py": "core/recovery_ai.py",
}


def merge_review_candidates(proposals: object, report: object) -> dict[str, Any]:
    if not isinstance(proposals, dict) or not isinstance(report, dict):
        raise ValueError("proposal and analyzer reports must be JSON objects")
    result = dict(proposals)
    result["review_only_proposals"] = []
    result["review_only_proposal_count"] = 0
    result["review_status"] = "NO_SAFE_CANDIDATE"
    result["review_reason"] = report.get("reason", "analyzer_report_unavailable")

    if report.get("status") != "REVIEW_REQUIRED":
        if report.get("status") not in {"NO_SAFE_CANDIDATE", "ANALYZER_BLOCKED"}:
            raise ValueError("unexpected catalog analyzer status")
        return result

    safety = report.get("safety")
    if not isinstance(safety, dict):
        raise ValueError("catalog analyzer safety contract is missing")
    if safety.get("read_only") is not True or safety.get("requires_human_review") is not True or safety.get("candidates_executable") is not False:
        raise ValueError("catalog analyzer safety contract is invalid")
    candidates = report.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CANDIDATES:
        raise ValueError("catalog analyzer candidate list is invalid")
    if report.get("candidate_count") != len(candidates):
        raise ValueError("catalog analyzer candidate count mismatch")

    seen: set[str] = set()
    review_rows = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("status") != "REVIEW_REQUIRED":
            raise ValueError("catalog analyzer candidate is invalid")
        task_id = candidate.get("id")
        target_test = candidate.get("target_test")
        source_function = candidate.get("source_function")
        evidence = candidate.get("evidence")
        fingerprint = candidate.get("fingerprint")
        if not isinstance(task_id, str) or not ID_RE.fullmatch(task_id) or task_id in seen:
            raise ValueError("catalog analyzer candidate ID is invalid or duplicated")
        if not isinstance(target_test, str) or target_test not in TARGETS:
            raise ValueError("catalog analyzer target test is not allowlisted")
        target_code = TARGETS[target_test]
        if not isinstance(source_function, str) or not FUNCTION_RE.fullmatch(source_function):
            raise ValueError("catalog analyzer source function is invalid")
        if not isinstance(evidence, str) or not re.fullmatch(re.escape(target_code) + r":[1-9][0-9]*", evidence):
            raise ValueError("catalog analyzer source evidence is invalid")
        if not isinstance(fingerprint, str) or not FINGERPRINT_RE.fullmatch(fingerprint):
            raise ValueError("catalog analyzer fingerprint is invalid")
        seen.add(task_id)
        instruction = (
            f"人手レビューで重複・間接カバレッジを確認した後に限り、{target_test} に "
            f"{target_code} の {source_function} ({evidence}) を対象とする回帰テストを1件追加する。"
            "この提案はレビュー専用で、登録済みタスク仕様・明示承認が整うまで実行不可。"
        )
        review_rows.append({
            "id": task_id,
            "status": "REVIEW_REQUIRED",
            "source": "catalog_exhaustion_analyzer",
            "target": target_code,
            "target_test": target_test,
            "source_function": source_function,
            "evidence": evidence,
            "fingerprint": fingerprint,
            "instruction": instruction,
            "execution_authorized": False,
        })
    result["review_only_proposals"] = review_rows
    result["review_only_proposal_count"] = len(review_rows)
    result["review_status"] = "REVIEW_REQUIRED"
    result["review_reason"] = "catalog_exhaustion_candidates_require_human_review"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--catalog-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        proposals = json.loads(args.proposals.read_text(encoding="utf-8"))
        report = json.loads(args.catalog_report.read_text(encoding="utf-8"))
        merged = merge_review_candidates(proposals, report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"catalog review proposal report stopped safely: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps({
        "trusted_status": merged.get("status"),
        "review_status": merged["review_status"],
        "review_only_proposal_count": merged["review_only_proposal_count"],
        "execution_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
