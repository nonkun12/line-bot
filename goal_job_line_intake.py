"""LINE-facing Goal proposal and one-time approval flow.

Only explicit Goal-prefixed messages enter this path. Proposals are inert until
the same authenticated LINE user approves them. Trusted grants are constructed
server-side and never accepted from message/model payloads.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import db
import goal_job_store
from goal_job_orchestrator import advance_goal

_GOAL_PREFIX = re.compile(r"^(?:goal\s*[:：]|目標\s*[:：]|goal\s+ai\s*[:：])\s*(.+)$", re.IGNORECASE | re.DOTALL)
_APPROVE = re.compile(r"^goal\s*(?:承認|approve)\s+([A-Za-z0-9._-]{6,100})$", re.IGNORECASE)
_MAX_OBJECTIVE_LENGTH = 2000
_PROPOSAL_TTL_HOURS = 24


def init_goal_line_intake() -> None:
    with db.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goal_line_proposals (
                proposal_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                objective TEXT NOT NULL,
                proposal_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                expires_at TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_goal_id TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_goal_line_proposals_user_status "
            "ON goal_line_proposals(user_id,status,created_at)"
        )


def parse_goal_intake(message: object) -> str | None:
    if not isinstance(message, str):
        return None
    match = _GOAL_PREFIX.fullmatch(message.strip())
    if not match:
        return None
    objective = match.group(1).strip()
    if not objective or len(objective) > _MAX_OBJECTIVE_LENGTH:
        return None
    return objective


def parse_goal_approval(message: object) -> str | None:
    if not isinstance(message, str):
        return None
    match = _APPROVE.fullmatch(message.strip())
    return match.group(1) if match else None


def _build_proposal(objective: str, proposal_id: str) -> dict[str, Any]:
    goal_id = f"line-goal-{proposal_id}"
    criterion_id = "goal_plan_ready"
    return {
        "goal_id": goal_id,
        "objective": objective,
        "success_criteria": [{
            "id": criterion_id,
            "description": "A scoped, dependency-ordered implementation plan exists and is independently reviewed.",
        }],
        "jobs": [{
            "id": "goal-plan",
            "criterion_id": criterion_id,
            "stage": "design",
            "instruction": (
                "Create a concise, sprint-oriented implementation plan for this Goal in "
                f"docs/goal-plans/{goal_id}.md. Objective: {objective}\n"
                "Include a Sprint Goal, small dependency-ordered JOBs, acceptance criteria, "
                "free-only tool choices, scope boundaries, and verification steps. "
                "This planning JOB writes only its plan document."
            ),
            "allowed_paths": [f"docs/goal-plans/{goal_id}.md"],
            "depends_on": [],
        }],
    }


def create_goal_proposal(user_id: str, objective: str) -> dict[str, Any]:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("authenticated LINE user is required")
    if not isinstance(objective, str) or not objective.strip() or len(objective) > _MAX_OBJECTIVE_LENGTH:
        raise ValueError("Goal objective is empty or too long")
    proposal_id = secrets.token_hex(6)
    proposal = _build_proposal(objective.strip(), proposal_id)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=_PROPOSAL_TTL_HOURS)).isoformat()
    init_goal_line_intake()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO goal_line_proposals(proposal_id,user_id,objective,proposal_json,expires_at) "
            "VALUES(?,?,?,?,?)",
            (proposal_id, user_id.strip(), objective.strip(), json.dumps(proposal, ensure_ascii=False), expires_at),
        )
    return {
        "proposal_id": proposal_id,
        "goal_id": proposal["goal_id"],
        "objective": objective.strip(),
        "expires_at": expires_at,
        "success_criteria": proposal["success_criteria"],
        "initial_job": proposal["jobs"][0]["id"],
    }


def _authorized_approver(user_id: str) -> bool:
    allowed = {
        item.strip()
        for item in (os.environ.get("GOAL_APPROVER_USER_IDS") or os.environ.get("DEV_ALLOWED_USER_IDS", "")).split(",")
        if item.strip()
    }
    return bool(user_id and user_id in allowed)


def approve_goal_proposal(user_id: str, proposal_id: str) -> dict[str, Any]:
    if not _authorized_approver(user_id):
        raise PermissionError("LINE user is not configured as an authorized Goal approver")
    init_goal_line_intake()
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT user_id,proposal_json,status,expires_at,approved_goal_id "
            "FROM goal_line_proposals WHERE proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if row is None or row[0] != user_id:
            raise PermissionError("proposal not found for this LINE user")
        if row[2] == "approved" and row[4]:
            return {"goal_id": row[4], "already_approved": True}
        if row[2] != "pending":
            raise ValueError("proposal is no longer pending")
        expiry = datetime.fromisoformat(row[3])
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            conn.execute(
                "UPDATE goal_line_proposals SET status='expired' WHERE proposal_id=? AND status='pending'",
                (proposal_id,),
            )
            raise ValueError("proposal expired; submit the Goal again")
        proposal = json.loads(row[1])
        goal_id = proposal["goal_id"]
        reserved = conn.execute(
            "UPDATE goal_line_proposals SET status='approving' "
            "WHERE proposal_id=? AND status='pending'",
            (proposal_id,),
        )
        if reserved.rowcount != 1:
            raise ValueError("proposal approval is already in progress")

    # Do not hold the proposal DB transaction while create_goal opens its own
    # connection; that would deadlock SQLite's writer lock.
    grant = {
        "grant_id": f"line-grant-{proposal_id}",
        "goal_id": goal_id,
        "active": True,
        "auto_approve_registered_jobs": True,
        "approved_by": user_id,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "max_jobs": 4,
        "allowed_stages": ["requirements", "design", "test", "review", "verify"],
        "allowed_path_prefixes": ["docs/"],
        "auto_merge": False,
        "auto_deploy": False,
    }
    try:
        goal_job_store.create_goal(proposal, user_id, grant)
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE goal_line_proposals SET status='approved',approved_goal_id=? "
                "WHERE proposal_id=? AND status='approving'",
                (goal_id, proposal_id),
            )
    except Exception:
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE goal_line_proposals SET status='pending' "
                "WHERE proposal_id=? AND status='approving'",
                (proposal_id,),
            )
        raise
    queued = advance_goal(goal_id)
    return {
        "goal_id": goal_id,
        "already_approved": False,
        "decision": queued.get("decision"),
        "reason": queued.get("reason"),
        "job_id": (queued.get("job_record") or {}).get("job_id"),
    }

def handle_goal_line_message(user_id: str, message: str) -> tuple[bool, str | None]:
    """Return (handled, reply); unrelated/read-only messages are untouched."""
    proposal_id = parse_goal_approval(message)
    if proposal_id:
        try:
            result = approve_goal_proposal(user_id, proposal_id)
        except PermissionError:
            return True, "Goal承認は許可されていません。登録済みの承認者アカウントから実行してください。"
        except ValueError as exc:
            return True, f"Goalを承認できませんでした: {exc}"
        if result.get("already_approved"):
            return True, f"このGoalは承認済みです。Goal ID: {result['goal_id']}"
        if result.get("decision") == "CHILD_JOB_QUEUED":
            return True, (
                f"Goalを承認し、最初のJOBを登録しました。Goal ID: {result['goal_id']} / "
                f"JOB ID: {result['job_id']}。実行は許可範囲内に限定され、マージ・デプロイは行いません。"
            )
        return True, (
            f"Goalは承認されましたが、初回JOBは保留です（{result.get('reason') or result.get('decision')}）。"
            f" Goal ID: {result['goal_id']}"
        )

    objective = parse_goal_intake(message)
    if objective is None:
        return False, None
    try:
        proposal = create_goal_proposal(user_id, objective)
    except Exception:
        return True, "Goal提案を保存できませんでした。時間をおいて再度お試しください。"
    return True, (
        "Goal提案を作成しました。まだ実行・コード変更は行っていません。\n"
        f"目的: {proposal['objective']}\n"
        f"Goal ID: {proposal['goal_id']}\n"
        f"初回JOB: {proposal['initial_job']}（docs/ 配下のSprint計画作成のみ）\n"
        f"承認する場合は「Goal承認 {proposal['proposal_id']}」と送信してください。\n"
        "承認期限: 24時間。マージ・デプロイ・秘密情報変更は対象外です。"
    )


__all__ = [
    "init_goal_line_intake",
    "parse_goal_intake",
    "parse_goal_approval",
    "create_goal_proposal",
    "approve_goal_proposal",
    "handle_goal_line_message",
]
