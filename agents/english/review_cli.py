"""Local, allowlisted human review CLI for English vocabulary candidates.

This module is intentionally not an HTTP or LINE command handler. Configure
ENGLISH_VOCAB_REVIEWER_IDS in the trusted runtime environment before use.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from agents.english.vocabulary_workflow import (
    approve_word_candidate,
    list_pending_candidates,
    reject_word_candidate,
)


def authorize_configured_reviewer(reviewer_id: str) -> bool:
    """Authorize only identities explicitly configured by the operator."""
    allowed = {
        item.strip()
        for item in os.environ.get("ENGLISH_VOCAB_REVIEWER_IDS", "").split(",")
        if item.strip()
    }
    return bool(reviewer_id and reviewer_id.strip() in allowed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review pending English vocabulary candidates.")
    parser.add_argument("--reviewer-id", required=True, help="Configured reviewer identity")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List pending candidates")
    approve = commands.add_parser("approve", help="Approve a candidate using reviewed JSON")
    approve.add_argument("candidate_id", type=int)
    approve.add_argument("--entry-file", required=True, type=Path)
    reject = commands.add_parser("reject", help="Reject a candidate with a reason")
    reject.add_argument("candidate_id", type=int)
    reject.add_argument("--reason", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not authorize_configured_reviewer(args.reviewer_id):
        print("拒否: configured human reviewer required", file=sys.stderr)
        return 2

    if args.command == "list":
        print(json.dumps(list_pending_candidates(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "approve":
        try:
            with args.entry_file.open(encoding="utf-8") as handle:
                entry = json.load(handle)
            word = approve_word_candidate(
                args.candidate_id,
                entry,
                args.reviewer_id,
                authorize_reviewer=authorize_configured_reviewer,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"承認失敗: {exc}", file=sys.stderr)
            return 1
        print(f"承認済み: {word}")
        return 0
    if args.command == "reject":
        try:
            reject_word_candidate(
                args.candidate_id,
                args.reviewer_id,
                args.reason,
                authorize_reviewer=authorize_configured_reviewer,
            )
        except (ValueError, PermissionError) as exc:
            print(f"却下失敗: {exc}", file=sys.stderr)
            return 1
        print(f"却下済み: #{args.candidate_id}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
