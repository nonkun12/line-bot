"""Merge validated catalog-exhaustion findings into the review-only candidate input.

This adapter never authorizes execution or mutates the task queue/catalog. Only
fixed allowlisted target/test pairs and validated analyzer evidence are accepted.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from scripts.autonomous_task_target_allowlist import TARGETS

MAX_HISTORY_CANDIDATES = 200
MAX_ANALYZER_CANDIDATES = 4
ID_PATTERN = re.compile(r"^review-coverage-gap-[a-f0-9]{10}$")
FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
FUNCTION_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
from scripts.autonomous_task_target_allowlist import TARGETS


def merge_candidates(history: object, report: object) -> list[dict[str, Any]]:
    if not isinstance(history, list):
        raise ValueError("history candidate input must be a JSON list")
    if not isinstance(report, dict):
        raise ValueError("catalog analyzer report must be a JSON object")

    result = [row for row in history[:MAX_HISTORY_CANDIDATES] if isinstance(row, dict)]
    if report.get("status") != "REVIEW_REQUIRED":
        return result
    safety = report.get("safety")
    if not isinstance(safety, dict) or safety.get("read_only") is not True or safety.get("requires_human_review") is not True or safety.get("candidates_executable") is not False:
        raise ValueError("catalog analyzer safety contract is invalid")
    candidates = report.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > MAX_ANALYZER_CANDIDATES:
        raise ValueError("catalog analyzer candidate list is invalid")
    if report.get("candidate_count") != len(candidates):
        raise ValueError("catalog analyzer candidate count mismatch")

    existing = {row.get("source_id") for row in result if row.get("source") == "self_improvement"}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("catalog analyzer candidate is invalid")
        task_id = candidate.get("id")
        target_test = candidate.get("target_test")
        evidence = candidate.get("evidence")
        source_function = candidate.get("source_function")
        fingerprint = candidate.get("fingerprint")
        if candidate.get("status") != "REVIEW_REQUIRED":
            raise ValueError("catalog analyzer candidate status is invalid")
        if not isinstance(task_id, str) or not ID_PATTERN.fullmatch(task_id):
            raise ValueError("catalog analyzer candidate ID is invalid")
        if not isinstance(fingerprint, str) or not FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise ValueError("catalog analyzer fingerprint is invalid")
        if not isinstance(source_function, str) or not FUNCTION_PATTERN.fullmatch(source_function):
            raise ValueError("catalog analyzer function evidence is invalid")
        if not isinstance(target_test, str):
            raise ValueError("catalog analyzer test target is invalid")
        matching = [pair for pair in TARGETS if pair[1] == target_test]
        if len(matching) != 1:
            raise ValueError("catalog analyzer test target is not allowlisted")
        target_code, _ = matching[0]
        if not isinstance(evidence, str) or not re.fullmatch(re.escape(target_code) + r":[1-9][0-9]*", evidence):
            raise ValueError("catalog analyzer source evidence is invalid")
        source_id = "catalog-exhaustion:" + task_id
        if source_id in existing:
            continue
        result.append({
            "source": "self_improvement",
            "source_id": source_id,
            "title": "Review uncovered regression-test coverage",
            "rationale": (
                f"Human review required: inspect {target_code} ({source_function}; {evidence}) "
                f"and consider a bounded regression test in {target_test}. "
                "The source is a heuristic candidate; check indirect coverage and duplication first. "
                "No queue admission or execution authorization is granted."
            ),
            "status": "proposed",
        })
        existing.add(source_id)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--catalog-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        history = json.loads(args.history.read_text(encoding="utf-8"))
        report = json.loads(args.catalog_report.read_text(encoding="utf-8"))
        rows = merge_candidates(history, report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"catalog review candidate adapter stopped safely: {type(exc).__name__}: {exc}")
        return 2
    print(f"REVIEW_CANDIDATE_INPUT_COUNT={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
