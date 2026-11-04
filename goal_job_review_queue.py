"""Leased, idempotent queue for independent local Goal reviews.

Review work is claimed by an authenticated Mac worker and evaluated locally.
A review never grants permissions or executes a child JOB.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import db
import goal_job_store
from goal_job_review import review_completed_goal
from goal_job_generation import generate_bounded_followup_job

_LEASE_MINUTES = 10


def _fingerprint(record: dict[str, Any], children: list[dict[str, Any]]) -> str:
    material = json.dumps(
        {"goal_id": record["goal_id"], "goal": record["goal"], "children": children},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def init_goal_review_queue() -> None:
    with db.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goal_review_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id TEXT NOT NULL,
                evidence_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                claim_token TEXT,
                lease_expires_at TEXT,
                result_json TEXT,
                decision_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(goal_id, evidence_fingerprint)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_goal_review_claims_status "
            "ON goal_review_claims(status, id)"
        )


def claim_next_goal_review() -> dict[str, Any] | None:
    """Claim one review snapshot; stale leases may be reclaimed safely."""
    init_goal_review_queue()
    with db.get_conn() as conn:
        goals = conn.execute(
            "SELECT goal_id FROM goal_chains WHERE status='active' ORDER BY updated_at, goal_id"
        ).fetchall()

    candidates = []
    for (goal_id,) in goals:
        record = goal_job_store.get_goal(goal_id)
        children = goal_job_store.get_goal_child_jobs(goal_id)
        if not record or not any(
            isinstance(child, dict) and child.get("status") in {"done", "completed"}
            and isinstance(child.get("evidence"), dict)
            and isinstance(child["evidence"].get("checks"), list)
            and child["evidence"]["checks"]
            for child in children
        ):
            continue
        candidates.append((record, children, _fingerprint(record, children)))

    for record, children, fingerprint in candidates:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(minutes=_LEASE_MINUTES)).isoformat()
        with db.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO goal_review_claims(goal_id,evidence_fingerprint,status) "
                "VALUES(?,?,'pending')",
                (record["goal_id"], fingerprint),
            )
            row = conn.execute(
                "SELECT id,status,lease_expires_at FROM goal_review_claims "
                "WHERE goal_id=? AND evidence_fingerprint=?",
                (record["goal_id"], fingerprint),
            ).fetchone()
            if row is None or row[1] in {"completed", "held"}:
                continue
            if row[1] == "running" and row[2]:
                try:
                    if datetime.fromisoformat(row[2]) > now:
                        continue
                except ValueError:
                    pass
            changed = conn.execute(
                "UPDATE goal_review_claims SET status='running',claim_token=?,lease_expires_at=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('pending','running')",
                (token, expires, row[0]),
            ).rowcount
            if changed != 1:
                continue
        criteria = record.get("goal", {}).get("success_criteria", [])
        return {
            "review_id": row[0],
            "claim_token": token,
            "goal_id": record["goal_id"],
            "objective": record.get("objective", ""),
            "success_criteria": criteria,
            "children": children,
            "evidence_fingerprint": fingerprint,
        }
    return None


def complete_goal_review(
    review_id: int,
    claim_token: str,
    criterion_results: dict[str, str],
) -> dict[str, Any]:
    """Persist one leased local review and advance at most one next JOB."""
    if type(review_id) is not int or review_id <= 0:
        raise ValueError("review_id must be a positive integer")
    if not isinstance(claim_token, str) or len(claim_token) < 20:
        raise ValueError("review claim token is invalid")
    if not isinstance(criterion_results, dict):
        raise ValueError("criterion_results must be an object")
    init_goal_review_queue()
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT goal_id,status,claim_token,lease_expires_at FROM goal_review_claims WHERE id=?",
            (review_id,),
        ).fetchone()
        if row is None or row[1] != "running" or not secrets.compare_digest(row[2] or "", claim_token):
            raise PermissionError("review claim is stale or already completed")
        try:
            if row[3] and datetime.fromisoformat(row[3]) < datetime.now(timezone.utc):
                raise PermissionError("review claim lease expired")
        except ValueError:
            raise PermissionError("review claim lease is invalid")
        conn.execute(
            "UPDATE goal_review_claims SET status='reviewing',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (review_id,),
        )

    try:
        decision = review_completed_goal(
            row[0],
            evaluator=lambda _record, _children: criterion_results,
            job_generator=generate_bounded_followup_job,
        )
    except Exception as exc:
        decision = {
            "decision": "HOLD",
            "reason": "review_processing_failed",
            "error_type": type(exc).__name__,
        }
    status = "completed" if decision.get("decision") != "HOLD" else "held"
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE goal_review_claims SET status=?,claim_token=NULL,lease_expires_at=NULL,"
            "result_json=?,decision_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='reviewing'",
            (
                status,
                json.dumps(criterion_results, ensure_ascii=False, sort_keys=True),
                json.dumps(decision, ensure_ascii=False, sort_keys=True, default=str),
                review_id,
            ),
        )
    return decision


__all__ = ["init_goal_review_queue", "claim_next_goal_review", "complete_goal_review"]
