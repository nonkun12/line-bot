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
from agents.video.scenario import build_scenario
from agents.media.audiovisual_game_sprint import build_audiovisual_game_sprint_plan
from agents.media.goal_job_chain_store import (
    GoalChainConflictError,
    create_or_resume_goal_chain,
    get_goal_chain,
    record_goal_chain_evidence,
)
from goal_job_orchestrator import advance_goal
from goal_job_generation import generate_bounded_followup_job

_GOAL_PREFIX = re.compile(r"^(?:goal\s*[:：]|目標\s*[:：]|goal\s+ai\s*[:：])\s*(.+)$", re.IGNORECASE | re.DOTALL)
_APPROVE = re.compile(r"^goal\s*(?:承認|approve)\s+([A-Za-z0-9._-]{6,100})$", re.IGNORECASE)
_GOAL_STATUS = re.compile(r"^(?:goal\s+status|goal状態)\s+([A-Za-z0-9._-]{1,100})$", re.IGNORECASE)
_GOAL_STAGE_APPROVE = re.compile(r"^(?:goal\s+stage\s+approve|goalステージ承認)\s+([A-Za-z0-9._-]{1,100})\s+([A-Za-z0-9._-]{1,80})$", re.IGNORECASE)
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
                approved_goal_id TEXT,
                approval_started_at TEXT
            )
        """)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(goal_line_proposals)").fetchall()
        }
        if "approval_started_at" not in columns:
            conn.execute("ALTER TABLE goal_line_proposals ADD COLUMN approval_started_at TEXT")
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


def parse_goal_chain_status(message: object) -> str | None:
    if not isinstance(message, str):
        return None
    match = _GOAL_STATUS.fullmatch(message.strip())
    return match.group(1) if match else None


def parse_goal_stage_approval(message: object) -> tuple[str, str] | None:
    if not isinstance(message, str):
        return None
    match = _GOAL_STAGE_APPROVE.fullmatch(message.strip())
    return (match.group(1), match.group(2)) if match else None


def _build_proposal(objective: str, proposal_id: str) -> dict[str, Any]:
    goal_id = f"line-goal-{proposal_id}"
    phases = [
        {
            "criterion_id": "music_video_foundation",
            "job_id": "sprint-01-music-video",
            "filename": "01-music-video-foundation.md",
            "title": "Sprint 1: Original music and audiovisual short work",
            "instruction": (
                "Define the first tangible increment: one original music piece and one short "
                "video whose scenario, emotional arc, pacing, color, motion, silence, and musical "
                "cues are designed together. Include composition, arrangement, MIDI/free soundfont "
                "workflow, storyboard, shot plan, free Blender/DaVinci/FFmpeg options, rights checks, "
                "acceptance criteria, and a small testable backlog."
            ),
        },
        {
            "criterion_id": "interactive_narrative",
            "job_id": "sprint-02-interactive",
            "filename": "02-interactive-narrative.md",
            "title": "Sprint 2: Interactive audiovisual narrative",
            "instruction": (
                "Design the next increment where viewer choices change story, visuals, and music. "
                "Specify branching narrative data, state transitions, audiovisual synchronization, "
                "prototype boundaries, acceptance criteria, and regression tests."
            ),
        },
        {
            "criterion_id": "simple_game_prototype",
            "job_id": "sprint-03-game-prototype",
            "filename": "03-simple-game-prototype.md",
            "title": "Sprint 3: Simple playable game",
            "instruction": (
                "Design a small browser-playable game prototype that grows from the established "
                "music, video, and interactive narrative foundations. Prefer free Godot tooling; "
                "define one core mechanic, a playable loop, input, UI, asset pipeline, and tests."
            ),
        },
        {
            "criterion_id": "full_game_roadmap",
            "job_id": "sprint-04-full-game",
            "filename": "04-full-game-roadmap.md",
            "title": "Sprint 4: Full original game roadmap",
            "instruction": (
                "Define the staged roadmap toward the final original full-featured game: distinctive "
                "ideas, world, mechanics, progression, content pipeline, music and video direction, "
                "browser delivery where feasible, quality gates, risks, and future Sprints."
            ),
        },
    ]
    scenario = build_scenario(
        objective[:500],
        title=objective[:120],
        premise=objective[:1000],
        duration_seconds=30,
        scene_count=4,
    )
    media_job = {
        "id": "media-01-audiovisual-draft",
        "criterion_id": "audiovisual_draft",
        "stage": "design",
        "instruction": (
            "Create the first local-only audiovisual draft bundle from this approved scenario: "
            "produce the scenario JSON, editable Japanese screenplay, storyboard, shot list, "
            "original music plan, MIDI, WAV preview, and synchronized edit decision list. "
            "Keep outputs as drafts; do not distribute externally or retrieve outside assets."
        ),
        "allowed_paths": [f"docs/goal-plans/{goal_id}/00-audiovisual-draft.md"],
        "depends_on": [],
        "executor": "mac_local_media.v1",
        "operation": "create_audiovisual_bundle",
        "scenario": scenario,
    }
    criteria = [
        {
            "id": "audiovisual_draft",
            "description": "A local draft scenario, Japanese screenplay, storyboard, shot list, original MIDI, WAV preview, music plan, and EDL have verified hashes.",
        },
        *[
            {
                "id": phase["criterion_id"],
                "description": f"An independently reviewable Sprint plan exists: {phase['title']}.",
            }
            for phase in phases
        ],
    ]
    jobs = [media_job]
    previous_job = media_job["id"]
    for phase in phases:
        path = f"docs/goal-plans/{goal_id}/{phase['filename']}"
        dependencies = [previous_job] if previous_job else []
        jobs.append({
            "id": phase["job_id"],
            "criterion_id": phase["criterion_id"],
            "stage": "design",
            "instruction": (
                f"Create a concise Sprint plan at {path}. Overall objective: {objective} "
                f"Sprint: {phase['title']} {phase['instruction']} "
                "Include a Sprint Goal, small dependency-ordered JOBs, measurable acceptance "
                "criteria, free-only tools, resource limits, safety boundaries, and verification. "
                "This JOB writes only its one plan document."
            ),
            "allowed_paths": [path],
            "depends_on": dependencies,
        })
        previous_job = phase["job_id"]
    return {
        "goal_id": goal_id,
        "objective": objective,
        "success_criteria": criteria,
        "jobs": jobs,
        "audiovisual_sprint_plan": build_audiovisual_game_sprint_plan(
            goal_id, objective[:1000], max_revision_iterations=2, target_platform="web"
        ),
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
    resume_existing = False
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT user_id,proposal_json,status,expires_at,approved_goal_id,approval_started_at "
            "FROM goal_line_proposals WHERE proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if row is None or row[0] != user_id:
            raise PermissionError("proposal not found for this LINE user")
        if row[2] == "approved" and row[4]:
            return {"goal_id": row[4], "already_approved": True}
        proposal = json.loads(row[1])
        goal_id = proposal["goal_id"]
        if row[2] == "approving":
            started = datetime.fromisoformat(row[5]) if row[5] else None
            lease_expired = (
                started is not None
                and started.tzinfo is not None
                and started <= datetime.now(timezone.utc) - timedelta(minutes=5)
            )
            if not lease_expired:
                raise ValueError("proposal approval is already in progress; retry shortly")
            existing_goal = conn.execute(
                "SELECT goal_id FROM goal_chains WHERE goal_id=?",
                (goal_id,),
            ).fetchone()
            if existing_goal:
                conn.execute(
                    "UPDATE goal_line_proposals SET status='approved',approved_goal_id=?,approval_started_at=NULL "
                    "WHERE proposal_id=? AND status='approving'",
                    (goal_id, proposal_id),
                )
                resume_existing = True
            else:
                conn.execute(
                    "UPDATE goal_line_proposals SET status='pending',approval_started_at=NULL "
                    "WHERE proposal_id=? AND status='approving'",
                    (proposal_id,),
                )
                row = (*row[:2], "pending", *row[3:])
        if not resume_existing:
            if row[2] != "pending":
                raise ValueError("proposal is no longer pending")
            expiry = datetime.fromisoformat(row[3])
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                conn.execute(
                    "UPDATE goal_line_proposals SET status='expired' WHERE proposal_id=? AND status='pending'",
                    (proposal_id,),
                )
                # Commit the terminal state before raising: sqlite3 rolls back
                # the connection context when an exception escapes it.
                conn.commit()
                raise ValueError("proposal expired; submit the Goal again")
            reserved = conn.execute(
                "UPDATE goal_line_proposals SET status='approving',approval_started_at=? "
                "WHERE proposal_id=? AND status='pending'",
                (datetime.now(timezone.utc).isoformat(), proposal_id),
            )
            if reserved.rowcount != 1:
                raise ValueError("proposal approval is already in progress")

    # Do not hold the proposal DB transaction while create_goal opens its own
    # connection; that would deadlock SQLite's writer lock.
    if resume_existing:
        create_or_resume_goal_chain(user_id, proposal["audiovisual_sprint_plan"])
        queued = advance_goal(goal_id)
        return {
            "goal_id": goal_id,
            "already_approved": True,
            "decision": queued.get("decision"),
            "reason": queued.get("reason"),
            "job_id": (queued.get("job_record") or {}).get("job_id"),
        }

    grant = {
        "grant_id": f"line-grant-{proposal_id}",
        "goal_id": goal_id,
        "active": True,
        "auto_approve_registered_jobs": True,
        "approved_by": user_id,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "max_jobs": 8,
        "allowed_stages": ["requirements", "design", "test", "review", "verify"],
        "allowed_path_prefixes": ["docs/"],
        "auto_merge": False,
        "auto_deploy": False,
    }
    try:
        goal_job_store.create_goal(proposal, user_id, grant)
        create_or_resume_goal_chain(user_id, proposal["audiovisual_sprint_plan"])
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE goal_line_proposals SET status='approved',approved_goal_id=?,approval_started_at=NULL "
                "WHERE proposal_id=? AND status='approving'",
                (goal_id, proposal_id),
            )
    except Exception:
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE goal_line_proposals SET status='pending',approval_started_at=NULL "
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
    status_goal_id = parse_goal_chain_status(message)
    if status_goal_id:
        chain = get_goal_chain(user_id, status_goal_id)
        if chain is None:
            return True, "このLINEユーザーが参照できるGoal連鎖は見つかりません。"
        state = chain["state"]
        return True, (
            f"Goal連鎖状態: {chain['goal_id']} / version {chain['version']}\n"
            f"READY: {', '.join(state['ready_job_ids']) or 'なし'}\n"
            f"承認待ち: {', '.join(state['awaiting_human_approval_job_ids']) or 'なし'}\n"
            f"HOLD: {', '.join(state['held_job_ids']) or 'なし'}"
        )

    stage_approval = parse_goal_stage_approval(message)
    if stage_approval:
        goal_id, stage_id = stage_approval
        if not _authorized_approver(user_id):
            return True, "Goalステージ承認は許可されていません。登録済みの承認者アカウントから実行してください。"
        chain = get_goal_chain(user_id, goal_id)
        if chain is None:
            return True, "このLINEユーザーが参照できるGoal連鎖は見つかりません。"
        snapshot = chain["state"]["snapshot"]
        stage_state = chain["state"]["state"].get(stage_id)
        completed_ids = list(snapshot["completed_job_ids"])
        approved_ids = list(snapshot["approved_gate_job_ids"])
        # The initial media bundle already contains the music and storyboard
        # artifacts. Once the scenario gate is approved, an explicit human
        # confirmation can complete and approve these two review stages.
        if stage_state == "READY" and stage_id in {"music", "visual"}:
            completed_ids.append(stage_id)
        elif stage_state != "AWAITING_HUMAN_APPROVAL":
            return True, "このステージはまだ人間レビュー可能な状態ではありません。"
        try:
            updated = record_goal_chain_evidence(
                user_id,
                goal_id,
                expected_version=chain["version"],
                completed_job_ids=completed_ids,
                approved_gate_job_ids=[*approved_ids, stage_id],
                held_job_ids=snapshot["held_job_ids"],
                event_type="human_approved",
            )
        except (ValueError, GoalChainConflictError, KeyError) as exc:
            return True, f"Goalステージを承認できませんでした: {exc}"
        ready = updated["state"]["ready_job_ids"]
        required_reviews = {"scenario", "music", "visual"}
        approved_reviews = set(updated["state"]["snapshot"]["approved_gate_job_ids"])
        continuation = None
        if required_reviews.issubset(approved_reviews):
            # The first Sprint JOB may proceed only after the initial local
            # scenario, music, and visual artifacts have all been reviewed.
            continuation = advance_goal(
                goal_id, job_generator=generate_bounded_followup_job
            )
        reply = (
            f"Goalステージを承認しました: {stage_id}\n"
            f"次に実行可能なステージ: {', '.join(ready) or 'なし'}"
        )
        if continuation is not None:
            reply += (
                f"\n初期クリエイティブ確認完了。次のJOB: "
                f"{continuation.get('decision')}"
            )
            job_record = continuation.get("job_record") or {}
            if job_record.get("job_id") is not None:
                reply += f" / JOB ID: {job_record['job_id']}"
        return True, reply

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
        f"初回JOB: {proposal['initial_job']}（承認後、Macで映像・音楽のローカル下書きを生成。外部配信なし）\n"
        f"承認する場合は「Goal承認 {proposal['proposal_id']}」と送信してください。\n"
        f"進捗確認: Goal状態 {proposal['goal_id']}\n"
        "成果物生成後はscenarioを承認し、その後musicとvisualを実際に確認してから各ステージを承認します。\n"
        "承認期限: 24時間。マージ・デプロイ・秘密情報変更は対象外です。"
    )


__all__ = [
    "init_goal_line_intake",
    "parse_goal_intake",
    "parse_goal_approval",
    "parse_goal_chain_status",
    "parse_goal_stage_approval",
    "create_goal_proposal",
    "approve_goal_proposal",
    "handle_goal_line_message",
]
