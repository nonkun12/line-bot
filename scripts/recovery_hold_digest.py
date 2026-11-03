"""Read-only Markdown digest of durable Recovery AI HOLD records."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import sys


LEGACY_REASON = "legacy_hold_reason_unavailable"


def build_digest(state: dict) -> str:
    if not isinstance(state, dict):
        raise ValueError("durable state must be an object")
    recovery = state.get("recovery_ai")
    if not isinstance(recovery, dict) or recovery.get("schema_version") != 1:
        raise ValueError("Recovery AI state is missing or has an unsupported schema")
    tasks = recovery.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("Recovery AI tasks must be an object")

    held = []
    for task_id, record in tasks.items():
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("Recovery AI task ID is invalid")
        if not isinstance(record, dict):
            raise ValueError(f"Recovery AI record is invalid for task: {task_id}")
        if record.get("held") is True:
            held.append((task_id, record))

    reasons = Counter(
        str(record.get("hold_reason") or LEGACY_REASON)
        for _, record in held
    )
    categories = Counter(
        str(record.get("last_category") or "missing")
        for _, record in held
    )
    missing_decision = sum(
        not record.get("last_decision_action") or not record.get("last_decision_reason")
        for _, record in held
    )

    lines = [
        "# Recovery AI HOLD digest",
        "",
        "> Read-only report. No HOLD state, queue, approval, or task record is modified.",
        "",
        f"- Registered Recovery AI task records: **{len(tasks)}**",
        f"- Currently held tasks: **{len(held)}**",
        f"- Held tasks missing decision action/reason: **{missing_decision}**",
        "",
        "## HOLD reasons",
        "",
        "| Reason | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| {reason} | {count} |" for reason, count in sorted(reasons.items()))
    lines.extend(["", "## Last failure categories", "", "| Category | Count |", "|---|---:|"])
    lines.extend(f"| {category} | {count} |" for category, count in sorted(categories.items()))
    lines.extend([
        "",
        "## Held task records",
        "",
        "| Task ID | Updated at | Last category | HOLD reason | Last decision |",
        "|---|---|---|---|---|",
    ])
    for task_id, record in sorted(held):
        updated = str(record.get("updated_at") or "unknown").replace("|", "\\|")
        category = str(record.get("last_category") or "missing").replace("|", "\\|")
        reason = str(record.get("hold_reason") or LEGACY_REASON).replace("|", "\\|")
        action = str(record.get("last_decision_action") or "missing").replace("|", "\\|")
        decision_reason = str(record.get("last_decision_reason") or "missing").replace("|", "\\|")
        lines.append(
            f"| {task_id} | {updated} | {category} | {reason} | {action}: {decision_reason} |"
        )
    if not held:
        lines.append("| — | — | — | — | — |")
    lines.extend([
        "",
        "## Safety interpretation",
        "",
        f"- {reasons.get(LEGACY_REASON, 0)} held records have no persisted original HOLD reason; their historical cause is unknown.",
        "- This report does not infer historical causes, clear HOLD, approve execution, or resume tasks.",
        "- Resume remains subject to the existing explicit human-approval and review gates.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="Path to durable autonomous loop state JSON")
    parser.add_argument("--output", help="Optional Markdown output path; defaults to stdout")
    args = parser.parse_args(argv)
    try:
        state = json.loads(Path(args.state).read_text(encoding="utf-8"))
        digest = build_digest(state)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"recovery_hold_digest: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if args.output:
        Path(args.output).write_text(digest, encoding="utf-8")
    else:
        sys.stdout.write(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
