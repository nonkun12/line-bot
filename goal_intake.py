"""LINE Goal intake. Proposals are inert until an allowlisted owner approves them."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import db
import goal_job_store

_GOAL = re.compile(r"^\s*(?:goal\s*[:：]|目標\s*[:：])\s*(.+?)\s*$", re.IGNORECASE)
_APPROVE = re.compile(r"^\s*(?:goal\s*approve|goal承認|目標承認)\s+([A-Za-z0-9_-]{8,40})\s*$", re.IGNORECASE)


def _allowed(user_id):
    allowed = {part.strip() for part in os.environ.get("DEV_ALLOWED_USER_IDS", "").split(",") if part.strip()}
    return bool(user_id and user_id in allowed)


def _init():
    goal_job_store.init_goal_job_store()
    with db.get_conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS goal_intake_proposals (
            proposal_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, objective TEXT NOT NULL,
            goal_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, approved_at TIMESTAMP
        )""")


def _contract(goal_id, objective):
    criterion = "sprint_plan_reviewed"
    return {
        "goal_id": goal_id,
        "objective": objective,
        "success_criteria": [{"id": criterion, "description": "Sprint計画に成果物・受入基準・依存関係・リスクが記録されている"}],
        "sprint": {"method": "agile", "sprint_number": 1,
                   "sprint_goal": "Goalを小さく検証可能な最初の成果物に分解する",
                   "review_required": True, "retrospective_required": True},
        "jobs": [{
            "id": "sprint-001-plan", "criterion_id": criterion, "stage": "requirements",
            "instruction": (
                "Create a concise Sprint 1 plan for this Goal. Include Sprint Goal, one small "
                "reviewable increment, acceptance criteria, dependencies, free-only tools, risks, "
                "and verification steps. Write only under docs/goal_sprints/ using a filename "
                "derived from the Goal ID. Limit all edits to the Sprint plan document; leave source code and service configuration untouched. "
                "Preserve the product sequence: original music and scenario-led audiovisual work, "
                "interactive narrative, simple game, then a full original game."
            ),
            "allowed_paths": ["docs/goal_sprints/"], "depends_on": []
        }]
    }


def _create(user_id, objective):
    objective = objective.strip()
    if not user_id or not objective or len(objective) > 500:
        raise ValueError("invalid Goal")
    _init()
    proposal_id = "goal-" + uuid.uuid4().hex[:16]
    goal = _contract(proposal_id, objective)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO goal_intake_proposals(proposal_id,user_id,objective,goal_json) VALUES(?,?,?,?)",
            (proposal_id, user_id, objective, json.dumps(goal, ensure_ascii=False, sort_keys=True))
        )
    return proposal_id


def _approve(user_id, proposal_id):
    _init()
    if not _allowed(user_id):
        return "Goalの実行承認権限がありません。"
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT user_id,goal_json,status,created_at FROM goal_intake_proposals WHERE proposal_id=?",
            (proposal_id,)
        ).fetchone()
        if row is None:
            return "Goal提案が見つかりません。"
        owner, goal_json, status, created_at = row
        if owner != user_id:
            return "作成者本人のみ承認できます。"
        if status == "approved":
            return f"Goal {proposal_id} は既に承認済みです。"
        if status not in {"pending", "approving"}:
            return "このGoal提案は承認できません。"
        if status == "pending":
            changed = conn.execute(
                "UPDATE goal_intake_proposals SET status='approving' "
                "WHERE proposal_id=? AND status='pending'", (proposal_id,)
            ).rowcount
            if changed != 1:
                return "Goal提案の承認状態が変わりました。もう一度確認してください。"

    # Keep this grant deterministic so an interrupted approval can safely resume.
    created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    goal = json.loads(goal_json)
    grant = {
        "grant_id": "grant-" + proposal_id.removeprefix("goal-"),
        "goal_id": proposal_id, "active": True, "approved_by": user_id,
        "expires_at": (created + timedelta(days=7)).isoformat(),
        "auto_approve_registered_jobs": True, "max_jobs": 1,
        "allowed_stages": ["requirements"], "allowed_path_prefixes": ["docs/"],
        "auto_merge": False, "auto_deploy": False
    }
    try:
        goal_job_store.create_goal(goal, user_id, grant)
        queued = goal_job_store.persist_child_job(proposal_id, goal["jobs"][0])
    except Exception:
        # Leave the proposal in 'approving'; the same owner can retry safely.
        raise
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE goal_intake_proposals SET status='approved',approved_at=CURRENT_TIMESTAMP "
            "WHERE proposal_id=? AND status='approving'", (proposal_id,)
        )
    return (f"Goal {proposal_id} を承認し、Sprint計画JOB {queued['job_id']} を登録しました。"
            "範囲は docs/goal_sprints/ の計画文書のみ、期限7日・最大1 JOBです。")


def handle_goal_intake(user_id, message):
    text = str(message or "")
    approval = _APPROVE.fullmatch(text)
    if approval:
        return _approve(str(user_id), approval.group(1))
    match = _GOAL.fullmatch(text)
    if not match:
        return None
    objective = match.group(1).strip()
    try:
        proposal_id = _create(str(user_id), objective)
    except Exception:
        return "Goal提案を保存できませんでした。"
    return (f"Goal提案 {proposal_id} を作成しました: {objective}\n"
            f"未実行です。承認する場合は「Goal承認 {proposal_id}」と送信してください。")


__all__ = ["handle_goal_intake"]
