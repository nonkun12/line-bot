"""Build a read-only Markdown digest of autonomous task review issues.

This report never changes issue labels, approvals, queues, catalog, or durable state.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SPEC_MARKER = "<!-- autonomous-task-spec -->"
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
EVIDENCE = re.compile(r"^([A-Za-z0-9_./-]+):([1-9][0-9]*)$")
FUNCTION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _spec(body: object) -> dict[str, str] | None:
    if not isinstance(body, str) or body.count(SPEC_MARKER) != 2:
        return None
    try:
        _, raw, _ = body.split(SPEC_MARKER)
        value = json.loads(raw.strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    task_id, evidence, function = value.get("id"), value.get("source_evidence"), value.get("source_function")
    # Older issues keep source evidence/function in prose rather than JSON.
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        return None
    return {"id": task_id}


def _labels(issue: dict[str, Any]) -> set[str]:
    labels = issue.get("labels", [])
    if not isinstance(labels, list):
        raise ValueError("issue labels must be a list")
    return {item["name"] for item in labels if isinstance(item, dict) and isinstance(item.get("name"), str)}


def _safe(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").replace("\r", " ").replace("`", "'")


def build_review_digest(issues: object) -> str:
    if not isinstance(issues, list):
        raise ValueError("issues must be a list")
    rows = []
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("issue entry must be an object")
        if issue.get("state") != "open":
            continue
        labels = _labels(issue)
        if "autonomous-task-candidate" not in labels:
            continue
        spec = _spec(issue.get("body"))
        if spec is None:
            continue
        number = issue.get("number")
        if type(number) is not int or number < 1:
            continue
        body = issue.get("body", "")
        evidence_match = re.search(r"^- Source evidence: `([^\n`]+)`", body, re.M)
        function_match = re.search(r"^- Source function: `([^\n`]+)`", body, re.M)
        evidence = evidence_match.group(1) if evidence_match else ""
        function = function_match.group(1) if function_match else ""
        source = evidence.rsplit(":", 1)[0] if EVIDENCE.fullmatch(evidence) else "(source unavailable)"
        approved = "autonomous-task-execution-approved" in labels
        catalog_approved = bool({"autonomous-task-catalog-approved", "autonomous-task-approved"} & labels)
        rows.append({
            "number": number, "title": issue.get("title", ""),
            "created": issue.get("created_at", ""), "updated": issue.get("updated_at", ""),
            "task_id": spec["id"], "source": source, "function": function,
            "execution_approved": approved, "catalog_approved": catalog_approved,
        })

    rows.sort(key=lambda x: (x["created"] or "9999", x["number"]))
    duplicate_titles = Counter(str(row["title"]) for row in rows)
    pending = [row for row in rows if not row["execution_approved"]]
    execution_approved = [row for row in rows if row["execution_approved"]]
    catalog_approved = [row for row in rows if row["catalog_approved"]]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source"]].append(row)

    lines = [
        "# Autonomous task review backlog",
        "",
        "> Read-only snapshot of open issues labeled `autonomous-task-candidate` with a valid task spec.",
        "> This digest does not grant approval, change labels, enqueue tasks, or modify durable state.",
        "",
        "## Summary",
        "",
        f"- Open review candidates: **{len(rows)}**",
        f"- Awaiting execution approval: **{len(pending)}**",
        f"- Execution-approved: **{len(execution_approved)}**",
        f"- Catalog-approved label present: **{len(catalog_approved)}**",
        f"- Ambiguous duplicate titles: **{sum(1 for n in duplicate_titles.values() if n > 1)} title group(s)**",
        "",
        "Execution approval and catalog approval are separate labels; neither count implies a task is registered, eligible, or executable.",
        "",
        "## Oldest first",
        "",
        "| Issue | Created | Source file | Function | Status | Title |",
        "|---:|---|---|---|---|---|",
    ]
    for row in rows:
        status = "execution-approved" if row["execution_approved"] else "review pending"
        if row["catalog_approved"]:
            status += "; catalog label"
        title = str(row["title"])
        if duplicate_titles[title] > 1:
            title += " ⚠ duplicate title"
        lines.append(
            f"| [#{row['number']}](https://github.com/nonkun12/line-bot/issues/{row['number']}) "
            f"| {_safe(row['created'])[:10]} | {_safe(row['source'])} | "
            f"{_safe(row['function'])} | {_safe(status)} | {_safe(title)} |"
        )
    lines.extend(["", "## Grouped by source file", ""])
    for source in sorted(grouped):
        lines.append(f"### `{_safe(source)}` ({len(grouped[source])})")
        for row in grouped[source]:
            marker = "approved" if row["execution_approved"] else "needs human review"
            lines.append(f"- [#{row['number']}]({_safe('https://github.com/nonkun12/line-bot/issues/' + str(row['number']))}) — {_safe(row['function'] or 'function unavailable')} ({marker})")
        lines.append("")
    lines.extend([
        "## Interpretation limits",
        "",
        "- This is an issue-backlog view only; it does not inspect the runtime queue, catalog registration, completed-task ledger, or Recovery AI HOLD state.",
        "- Duplicate titles are flagged for disambiguation; issues are not merged or closed automatically.",
        "- Human reviewers must inspect each issue's evidence and existing test coverage before applying any approval label.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        issues = json.loads(args.issues.read_text(encoding="utf-8"))
        digest = build_review_digest(issues)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(digest, encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"AUTONOMOUS_TASK_REVIEW_DIGEST_BLOCKED: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps({"status": "READ_ONLY_DIGEST_CREATED", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
