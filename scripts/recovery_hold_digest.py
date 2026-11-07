"""Read-only Markdown digest of durable Recovery AI BLOCKED and FAILED records."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import sys
import re


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
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", task_id):
            raise ValueError("Recovery AI task ID is invalid")
        if not isinstance(record, dict):
            raise ValueError(f"Recovery AI record is invalid for task: {task_id}")
        if record.get("held") is True:
            held.append((task_id, record))

    preflight = recovery.get("preflight_blocked", {})
    if not isinstance(preflight, dict):
        raise ValueError("Recovery AI preflight BLOCKED ledger must be an object")
    if len(preflight) > 200:
        raise ValueError("Recovery AI preflight BLOCKED ledger exceeds its bound")
    preflight_events = []
    for fingerprint, event in preflight.items():
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ValueError("Recovery AI preflight fingerprint is invalid")
        if not isinstance(event, dict):
            raise ValueError("Recovery AI preflight event is invalid")
        task_id = event.get("task_id")
        reason_code = event.get("reason_code")
        prerequisite_id = event.get("prerequisite_id")
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", task_id):
            raise ValueError("Recovery AI preflight task ID is invalid")
        if not isinstance(reason_code, str) or not re.fullmatch(
            r"(?:control_tower_gate|control_tower_rea|control_tower_selector):[A-Za-z0-9._-]{1,80}|control_tower_head_changed",
            reason_code,
        ):
            raise ValueError("Recovery AI preflight reason code is invalid")
        if prerequisite_id is not None and (
            not isinstance(prerequisite_id, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", prerequisite_id)
        ):
            raise ValueError("Recovery AI preflight prerequisite ID is invalid")
        if event.get("requires_human_review") is not True:
            raise ValueError("Recovery AI preflight event must require human review")
        if event.get("status") != "PENDING_PREREQUISITE_OR_REVIEW":
            raise ValueError("Recovery AI preflight event status is invalid")
        preflight_events.append((task_id, event))

    reasons = Counter(
        str(record.get("hold_reason") or LEGACY_REASON)
        for _, record in held
    )
    categories = Counter(
        str(record.get("last_category") or "missing")
        for _, record in held
    )
    # Recovery records are evidence, not authorization. A non-held task with a
    # persisted failure decision is reported as FAILED backlog; a held task or
    # a task awaiting post-resume review is reported as BLOCKED.
    failed = [
        (task_id, record) for task_id, record in tasks.items()
        if not record.get("held", False)
        and int(record.get("consecutive_failures", 0) or 0) > 0
        and record.get("last_category")
    ]
    review_required = [
        (task_id, record) for task_id, record in tasks.items()
        if record.get("resume_requires_review") is True
    ]
    recovery_decisions = Counter(
        str(record.get("last_decision_action") or "missing")
        for _, record in tasks.items()
        if record.get("last_decision_action")
    )
    missing_decision = sum(
        not record.get("last_decision_action") or not record.get("last_decision_reason")
        for _, record in held
    )

    lines = [
        "# Recovery AI BLOCKED / FAILED digest",
        "",
        "> Read-only report. No HOLD state, queue, approval, or task record is modified.",
        "",
        f"- Registered Recovery AI task records: **{len(tasks)}**",
        f"- Currently held tasks (BLOCKED / human review): **{len(held)}**",
        f"- Failed tasks awaiting bounded recovery or review: **{len(failed)}**",
        f"- Tasks awaiting post-resume human review: **{len(review_required)}**",
        f"- Held tasks missing decision action/reason: **{missing_decision}**",
        f"- Persisted preflight BLOCKED events (separate from failures): **{len(preflight_events)}**",
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
    lines.extend(["", "## BLOCKED / FAILED inventory", "",
        "| State | Task ID | Updated at | Failures | Category | Decision | Reason |",
        "|---|---|---|---:|---|---|---|"])
    inventory = [("BLOCKED", task_id, record) for task_id, record in held]
    inventory.extend(("FAILED", task_id, record) for task_id, record in failed)
    inventory.extend(("REVIEW_REQUIRED", task_id, record) for task_id, record in review_required if not record.get("held"))
    for task_id, event in preflight_events:
        values = [
            "PREFLIGHT_BLOCKED", task_id, str(event.get("last_seen_at") or "unknown"),
            "0", "preflight", "HUMAN_REVIEW_REQUIRED", str(event.get("reason_code")),
        ]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    for state, task_id, record in sorted(inventory, key=lambda item: (item[0], item[1])):
        values = [
            state, task_id, str(record.get("updated_at") or "unknown"),
            str(record.get("consecutive_failures", 0)),
            str(record.get("last_category") or "unknown"),
            str(record.get("last_decision_action") or "missing"),
            str(record.get("last_decision_reason") or record.get("hold_reason") or "missing"),
        ]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    if not inventory:
        lines.append("| — | — | — | — | — | — | — |")
    lines.extend(["", "## Last recovery decisions", "", "| Decision | Count |", "|---|---:|"])
    lines.extend(f"| {action} | {count} |" for action, count in sorted(recovery_decisions.items()))
    lines.extend([
        "",
        "## Safety interpretation",
        "",
        f"- {reasons.get(LEGACY_REASON, 0)} held records have no persisted original HOLD reason; their historical cause is unknown.",
        "- RETRY / REPAIR_ONCE are persisted Recovery AI decisions, not permission to execute; the runtime must still enforce cooldowns, attempt bounds, preflight, and catalog approval.",
        "- PREFLIGHT_BLOCKED events are separate from task failures and never increment failure counters. They are not automatically retried; prerequisite resolution and human review remain mandatory.",
        "- BLOCKED / REVIEW_REQUIRED items are not automatically retried. Explicit prerequisites and human review remain mandatory.",
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
