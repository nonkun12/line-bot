"""Create bounded, review-only GitHub Issue drafts from validated exhaustion findings.

The output contains test-only task specs marked for human review. This module
never creates issues, edits the queue/catalog, or grants execution approval.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

MAX_DRAFTS = 4
TASK_ID = re.compile(r"^review-coverage-gap-[a-f0-9]{10}$")
FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")
FUNCTION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
SPEC_MARKER = "<!-- autonomous-task-spec -->"
TARGETS = {
    ("core/line_development_runtime.py", "tests/test_line_development_runtime.py"),
    ("core/agent_runtime.py", "tests/test_agent_runtime.py"),
    ("core/management_router.py", "tests/test_management_router.py"),
    ("core/control_tower_orchestrator.py", "tests/test_control_tower_orchestrator.py"),
    ("core/recovery_ai.py", "tests/test_recovery_ai.py"),
}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid issue-draft input") from exc


def _existing_task_ids(issues: object) -> set[str]:
    if not isinstance(issues, list):
        raise ValueError("existing issues must be a list")
    found: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("existing issue entry must be an object")
        body = issue.get("body")
        if not isinstance(body, str) or body.count(SPEC_MARKER) != 2:
            continue
        try:
            _, raw, _ = body.split(SPEC_MARKER)
            spec = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        if isinstance(spec, dict) and isinstance(spec.get("id"), str) and TASK_ID.fullmatch(spec["id"]):
            found.add(spec["id"])
    return found


def build_issue_drafts(report: object, issues: object) -> list[dict[str, str]]:
    if not isinstance(report, dict):
        raise ValueError("analyzer report must be an object")
    if report.get("status") != "REVIEW_REQUIRED":
        if report.get("status") == "NO_SAFE_CANDIDATE" and report.get("candidate_count") == 0 and report.get("candidates") == []:
            return []
        raise ValueError("analyzer report is not reviewable")
    safety = report.get("safety")
    if not isinstance(safety, dict) or safety.get("read_only") is not True or safety.get("requires_human_review") is not True or safety.get("candidates_executable") is not False:
        raise ValueError("analyzer safety contract is invalid")
    candidates = report.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_DRAFTS or report.get("candidate_count") != len(candidates):
        raise ValueError("analyzer candidate count is invalid")

    existing = _existing_task_ids(issues)
    seen: set[str] = set()
    drafts: list[dict[str, str]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("analyzer candidate must be an object")
        task_id = candidate.get("id")
        test_path = candidate.get("target_test")
        evidence = candidate.get("evidence")
        function = candidate.get("source_function")
        fingerprint = candidate.get("fingerprint")
        matching = [pair for pair in TARGETS if pair[1] == test_path]
        if (
            not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id)
            or len(matching) != 1
            or not isinstance(function, str) or not FUNCTION.fullmatch(function)
            or not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint)
            or not isinstance(evidence, str)
            or not re.fullmatch(re.escape(matching[0][0]) + r":[1-9][0-9]*", evidence)
            or candidate.get("status") != "REVIEW_REQUIRED"
        ):
            raise ValueError("analyzer candidate evidence is invalid")
        if task_id in seen:
            continue
        seen.add(task_id)
        if task_id in existing:
            continue

        instruction = (
            f"人手レビュー後に限り、{test_path} に {function} ({evidence}) の"
            "境界条件を検証する新しい回帰テストを1件追加してください。"
            "まず既存テストと間接カバレッジを確認し、重複する場合は変更せず理由を報告してください。"
            "変更は指定テストファイル1つだけ。実装コード・workflow・catalog・stateは変更禁止。"
            "外部通信・シークレット参照・OS操作・マージ・デプロイは禁止。"
        )
        spec = {"id": task_id, "instruction": instruction, "allowed_paths": [test_path]}
        body = (
            "## 自動生成されたレビュー専用タスク候補\n\n"
            "このIssueは候補の記録です。**実行承認ではありません。**\n"
            "人手で既存テストとの重複・間接カバレッジを確認してください。\n\n"
            f"- Source evidence: `{evidence}`\n"
            f"- Source function: `{function}`\n"
            f"- Analyzer fingerprint: `{fingerprint}`\n"
            "- Allowed change: 指定されたテストファイル1つのみ\n"
            "- Queue admission: not authorized\n\n"
            f"{SPEC_MARKER}\n{json.dumps(spec, ensure_ascii=False, sort_keys=True)}\n{SPEC_MARKER}"
        )
        drafts.append({
            "title": f"Review-only test task: {function}"[:180],
            "body": body,
            "task_id": task_id,
        })
    return drafts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        drafts = build_issue_drafts(_load(args.report), _load(args.issues))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(drafts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"AUTONOMOUS_TASK_ISSUE_DRAFTS_BLOCKED: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps({"draft_count": len(drafts), "task_ids": [row["task_id"] for row in drafts]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
