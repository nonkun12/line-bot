#!/usr/bin/env python3
"""Independent, fail-closed QA gate for pull-request test evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PROTECTED_PATHS = (
    ".github/workflows/",
    "core/creator_critic.py",
    "core/quality_runtime.py",
    "scripts/run_creator_critic_github.py",
    "tests/",
)


def junit_counts(path: str | Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    failures = errors = skipped = 0
    for case in cases:
        failures += len(case.findall("failure"))
        errors += len(case.findall("error"))
        skipped += len(case.findall("skipped"))
    total = len(cases)
    return {
        "total": total,
        "passed": total - failures - errors - skipped,
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
    }


def changed_paths(base_sha: str, head_sha: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}...{head_sha}"],
        check=True, capture_output=True, text=True,
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def is_protected(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in PROTECTED_PATHS)


def evaluate(
    *, base_sha: str, head_sha: str, actual_sha: str,
    base_counts: dict[str, int], head_counts: dict[str, int],
    files: list[str], allow_protected: bool = False,
) -> dict:
    reasons: list[str] = []
    if not base_sha or not head_sha or actual_sha != head_sha:
        reasons.append("HEAD_SHA_MISMATCH")
    if base_counts["failed"] or base_counts["errors"]:
        reasons.append("BASE_TESTS_NOT_CLEAN")
    if head_counts["failed"] or head_counts["errors"]:
        reasons.append("HEAD_TESTS_NOT_CLEAN")
    if head_counts["total"] == 0 or base_counts["total"] == 0:
        reasons.append("TEST_EVIDENCE_EMPTY")
    if head_counts["total"] < base_counts["total"]:
        reasons.append("TOTAL_TEST_COUNT_DECREASED")
    if head_counts["passed"] < base_counts["passed"]:
        reasons.append("PASSED_TEST_COUNT_DECREASED")
    if head_counts["skipped"] > base_counts["skipped"]:
        reasons.append("SKIPPED_TEST_COUNT_INCREASED")
    protected = [path for path in files if is_protected(path)]
    if protected:
        reasons.append("PROTECTED_PATHS_REQUIRE_MAINTAINER_REVIEW")
    return {
        "schema_version": 1,
        "quality_status": "PASS" if not reasons else "HOLD",
        "base_sha": base_sha,
        "head_sha": head_sha,
        "actual_sha": actual_sha,
        "base_tests": base_counts,
        "head_tests": head_counts,
        "changed_files": files,
        "protected_files": protected,
        "protected_changes_approved": False,
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--base-junit", required=True)
    parser.add_argument("--head-junit", required=True)
    parser.add_argument("--output", default="qa.json")
    args = parser.parse_args()

    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    report = evaluate(
        base_sha=args.base_sha,
        head_sha=args.head_sha,
        actual_sha=actual,
        base_counts=junit_counts(args.base_junit),
        head_counts=junit_counts(args.head_junit),
        files=changed_paths(args.base_sha, args.head_sha),
    )
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["quality_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
