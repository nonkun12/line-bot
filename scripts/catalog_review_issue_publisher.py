"""Build review-only GitHub Issue payloads from catalog exhaustion analysis.

No network calls or execution authorization are performed by this module. The
workflow may publish returned payloads as candidate-labeled Issues for human
review; runtime admission still requires a registered catalog spec and approval.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SPEC_MARKER = "<!-- autonomous-task-spec -->"
CANDIDATE_MARKER = "<!-- catalog-exhaustion-candidate:"
MAX_CANDIDATES = 4
ID_PATTERN = re.compile(r"^review-coverage-gap-[a-f0-9]{10}$")
FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
TARGETS = {
    ("core/line_development_runtime.py", "tests/test_line_development_runtime.py"),
    ("core/agent_runtime.py", "tests/test_agent_runtime.py"),
    ("core/management_router.py", "tests/test_management_router.py"),
    ("core/control_tower_orchestrator.py", "tests/test_control_tower_orchestrator.py"),
    ("core/recovery_ai.py", "tests/test_recovery_ai.py"),
}


def build_issue_payloads(report: object, existing_issues: object) -> list[dict[str, Any]]:
    if not isinstance(report, dict):
        raise ValueError("analyzer report must be an object")
    if not isinstance(existing_issues, list):
        raise ValueError("existing issues must be a list")
    if report.get("status") != "REVIEW_REQUIRED":
        return []
    safety = report.get("safety")
    if not isinstance(safety, dict) or safety.get("read_only") is not True or safety.get("requires_human_review") is not True or safety.get("candidates_executable") is not False:
        raise ValueError("analyzer safety contract is invalid")
    candidates = report.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES or report.get("candidate_count") != len(candidates):
        raise ValueError("analyzer candidate list/count is invalid")

    existing_ids: set[str] = set()
    for issue in existing_issues:
        if not isinstance(issue, dict):
            continue
        body = issue.get("body")
        if not isinstance(body, str):
            continue
        for match in re.finditer(r"<!-- catalog-exhaustion-candidate:(review-coverage-gap-[a-f0-9]{10}) -->", body):
            existing_ids.add(match.group(1))

    payloads = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("candidate is invalid")
        task_id = candidate.get("id")
        fingerprint = candidate.get("fingerprint")
        target_test = candidate.get("target_test")
        evidence = candidate.get("evidence")
        source_function = candidate.get("source_function")
        instruction = candidate.get("instruction")
        if not isinstance(task_id, str) or not ID_PATTERN.fullmatch(task_id):
            raise ValueError("candidate ID is invalid")
        if task_id in seen_ids:
            raise ValueError("duplicate candidate ID")
        seen_ids.add(task_id)
        if not isinstance(fingerprint, str) or not FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise ValueError("candidate fingerprint is invalid")
        matching = [pair for pair in TARGETS if pair[1] == target_test]
        if len(matching) != 1:
            raise ValueError("candidate test target is not allowlisted")
        target_code, _ = matching[0]
        if not isinstance(evidence, str) or not re.fullmatch(re.escape(target_code) + r":[1-9][0-9]*", evidence):
            raise ValueError("candidate source evidence is invalid")
        if not isinstance(source_function, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", source_function):
            raise ValueError("candidate source function is invalid")
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 2000:
            raise ValueError("candidate instruction is invalid")
        if candidate.get("status") != "REVIEW_REQUIRED":
            raise ValueError("candidate status is invalid")
        if task_id in existing_ids:
            continue

        spec = {
            "id": task_id,
            "instruction": instruction.strip(),
            "allowed_paths": [target_test],
        }
        spec_json = json.dumps(spec, ensure_ascii=False, indent=2)
        body = (
            "## Review-only catalog-exhaustion proposal\n\n"
            f"{CANDIDATE_MARKER}{task_id} -->\n"
            "**Status:** review required; this Issue does not authorize execution.\n\n"
            f"- Source: `{target_code}`\n"
            f"- Evidence: `{evidence}`\n"
            f"- Symbol: `{source_function}`\n"
            f"- Test target: `{target_test}`\n"
            f"- Analyzer fingerprint: `{fingerprint}`\n\n"
            "Please check for indirect coverage, duplicate tests, and whether the proposed boundary case is meaningful. "
            "Only the listed test file may be changed by a future task. A human must review the proposal; "
            "execution additionally requires an exact registered catalog specification and the existing approval gate.\n\n"
            f"{SPEC_MARKER}\n{spec_json}\n{SPEC_MARKER}\n"
        )
        payloads.append({
            "id": task_id,
            "title": f"Review-only regression-test proposal: {task_id}",
            "body": body,
            "labels": ["autonomous-task-candidate"],
            "execution_authorized": False,
        })
    return payloads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--existing-issues", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        issues = json.loads(args.existing_issues.read_text(encoding="utf-8"))
        payloads = build_issue_payloads(report, issues)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payloads, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"catalog review Issue publisher stopped safely: {type(exc).__name__}: {exc}")
        return 2
    print(f"REVIEW_ISSUE_PROPOSALS={len(payloads)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
