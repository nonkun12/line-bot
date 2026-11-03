"""Durable, idempotent persistence adapter for Goal AI child JOB chains.

The caller must pass a grant that was explicitly approved and retrieved from a
trusted server-side source. Goal/model payloads are never treated as grants.
This adapter only persists allowlisted goal_child jobs; it does not execute,
merge, deploy, or clear an existing HOLD.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import db
from core.autonomy_policy import evaluate_job_autonomy

_ALLOWED_GRANT_ROOTS = {"tests/", "uhip/tests/", "docs/", "agents/", "core/", "scripts/"}
_ALLOWED_STATES = {"PASS", "FAIL", "UNKNOWN"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_grant(grant: object, goal_id: str) -> dict[str, Any]:
    if not isinstance(grant, dict):
        raise ValueError("trusted autonomy grant is required")
    expires_at = grant.get("expires_at")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) if isinstance(expires_at, str) else None
    except ValueError:
        expiry = None
    stages = grant.get("allowed_stages")
    roots = grant.get("allowed_path_prefixes")
    max_jobs = grant.get("max_jobs")
    if (
        not isinstance(grant.get("grant_id"), str) or not grant["grant_id"].strip()
        or grant.get("goal_id") != goal_id
        or grant.get("active") is not True
        or grant.get("auto_approve_registered_jobs") is not True
        or not isinstance(grant.get("approved_by"), str) or not grant["approved_by"].strip()
        or expiry is None or expiry.tzinfo is None or expiry <= datetime.now(timezone.utc)
        or type(max_jobs) is not int or not 1 <= max_jobs <= 50
        or not isinstance(stages, list) or not stages
        or any(not isinstance(stage, str) or stage not in {"requirements", "design", "implementation", "test", "review", "fix", "verify"} for stage in stages)
        or len(stages) != len(set(stages))
        or not isinstance(roots, list) or not roots
        or any(not isinstance(root, str) or root not in _ALLOWED_GRANT_ROOTS for root in roots)
        or len(roots) != len(set(roots))
        or grant.get("auto_merge", False) is not False
        or grant.get("auto_deploy", False) is not False
    ):
        raise ValueError("trusted autonomy grant is invalid, expired, or outside policy")
    return dict(grant)


def init_goal_job_store() -> None:
    """Create additive Goal tables; safe to call repeatedly during app startup."""
    with db.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goal_chains (
                goal_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                objective TEXT NOT NULL,
                goal_json TEXT NOT NULL,
                grant_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goal_chain_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id TEXT NOT NULL,
                goal_job_key TEXT NOT NULL,
                criterion_id TEXT NOT NULL,
                job_id INTEGER NOT NULL UNIQUE,
                evidence_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(goal_id, goal_job_key),
                FOREIGN KEY(goal_id) REFERENCES goal_chains(goal_id),
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(goal_chain_jobs)").fetchall()}
        if "evidence_json" not in columns:
            conn.execute("ALTER TABLE goal_chain_jobs ADD COLUMN evidence_json TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_goal_chain_jobs_goal_id ON goal_chain_jobs(goal_id, id)")


def create_goal(goal: object, user_id: str, approved_grant: object) -> dict[str, Any]:
    """Persist a goal and its one-time, goal-scoped approval grant.

    Repeating the exact same request is idempotent. Reusing a goal_id with
    different content or a different grant is rejected rather than overwritten.
    """
    if not isinstance(goal, dict):
        raise ValueError("goal must be an object")
    goal_id = goal.get("goal_id")
    objective = goal.get("objective")
    criteria = goal.get("success_criteria")
    if not isinstance(goal_id, str) or not goal_id.strip() or len(goal_id) > 100:
        raise ValueError("goal_id is invalid")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id is required")
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError("objective is required")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("success_criteria are required")
    grant = _validate_grant(approved_grant, goal_id)
    goal_payload = _json(goal)
    grant_payload = _json(grant)
    initial_evidence = _json({item["id"]: "FAIL" for item in criteria if isinstance(item, dict) and isinstance(item.get("id"), str)})
    init_goal_job_store()
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT user_id, goal_json, grant_json FROM goal_chains WHERE goal_id=?",
            (goal_id,),
        ).fetchone()
        if existing:
            if existing != (user_id, goal_payload, grant_payload):
                raise ValueError("goal_id already exists with different content or grant")
        else:
            conn.execute(
                "INSERT INTO goal_chains(goal_id,user_id,objective,goal_json,grant_json,evidence_json) VALUES(?,?,?,?,?,?)",
                (goal_id, user_id, objective.strip(), goal_payload, grant_payload, initial_evidence),
            )
    return get_goal(goal_id)


def get_goal(goal_id: str) -> dict[str, Any] | None:
    init_goal_job_store()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT goal_id,user_id,objective,goal_json,grant_json,evidence_json,status,created_at,updated_at "
            "FROM goal_chains WHERE goal_id=?",
            (goal_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "goal_id": row[0], "user_id": row[1], "objective": row[2],
        "goal": json.loads(row[3]), "autonomy_grant": json.loads(row[4]),
        "criterion_results": json.loads(row[5]), "status": row[6],
        "created_at": row[7], "updated_at": row[8],
    }


def persist_child_job(goal_id: str, job: object, *, parent_job_key: str | None = None) -> dict[str, Any]:
    """Create exactly one pending goal_child job for a registered Goal JOB key."""
    if not isinstance(job, dict):
        raise ValueError("job must be an object")
    key = job.get("id")
    criterion_id = job.get("criterion_id")
    if not isinstance(key, str) or not key.strip() or not isinstance(criterion_id, str) or not criterion_id.strip():
        raise ValueError("job id and criterion_id are required")
    init_goal_job_store()
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        goal_row = conn.execute(
            "SELECT grant_json,status,goal_json FROM goal_chains WHERE goal_id=?",
            (goal_id,),
        ).fetchone()
        if goal_row is None:
            raise ValueError("goal not found")
        if goal_row[1] != "active":
            raise ValueError("goal is not active")
        existing = conn.execute(
            "SELECT job_id FROM goal_chain_jobs WHERE goal_id=? AND goal_job_key=?",
            (goal_id, key),
        ).fetchone()
        if existing:
            row = conn.execute(
                "SELECT id,status,parent_job_id FROM jobs WHERE id=?",
                (existing[0],),
            ).fetchone()
            return {"job_id": existing[0], "status": row[1], "parent_job_id": row[2], "created": False}

        goal_contract = json.loads(goal_row[2])
        registered_job = next((item for item in goal_contract.get("jobs", [])
                               if isinstance(item, dict) and item.get("id") == key), None)
        if not isinstance(registered_job, dict):
            raise PermissionError("child JOB is not registered in the persisted Goal contract")
        for field in ("criterion_id", "stage", "allowed_paths", "depends_on"):
            default = [] if field == "depends_on" else None
            if registered_job.get(field, default) != job.get(field, default):
                raise PermissionError("child JOB differs from the persisted Goal contract")
        if registered_job.get("instruction", "").strip() != job.get("instruction", "").strip():
            raise PermissionError("child JOB instruction differs from the persisted Goal contract")
        grant = json.loads(goal_row[0])
        grant = _validate_grant(grant, goal_id)
        decision = evaluate_job_autonomy(job)
        paths = job.get("allowed_paths")
        in_grant = (
            job.get("stage") in grant["allowed_stages"]
            and isinstance(paths, list) and bool(paths)
            and all(isinstance(path, str) and any(path.startswith(root) for root in grant["allowed_path_prefixes"]) for path in paths)
        )
        if decision.get("decision") != "AUTO_APPROVE" or not in_grant:
            raise PermissionError("job is outside the trusted autonomy grant or risk policy")

        registered = conn.execute(
            "SELECT COUNT(*) FROM goal_chain_jobs WHERE goal_id=?",
            (goal_id,),
        ).fetchone()[0]
        if registered >= grant["max_jobs"]:
            raise PermissionError("goal autonomy job budget exhausted")

        dependencies = job.get("depends_on", [])
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
            raise ValueError("depends_on must be a list of Goal JOB keys")
        if parent_job_key is not None and parent_job_key not in dependencies:
            raise ValueError("parent_job_key must be declared in depends_on")
        parent_job_id = None
        for dependency_key in dependencies:
            parent = conn.execute(
                "SELECT link.job_id,j.status FROM goal_chain_jobs link "
                "JOIN jobs j ON j.id=link.job_id WHERE link.goal_id=? AND link.goal_job_key=?",
                (goal_id, dependency_key),
            ).fetchone()
            if parent is None:
                raise ValueError("dependency Goal JOB has not been persisted")
            if parent[1] not in {"done", "completed"} and not (
                job.get("stage") == "fix" and parent[1] in {"failed", "held"}
            ):
                raise ValueError("dependency Goal JOB is not complete or eligible for repair")
            if parent_job_id is None:
                parent_job_id = parent[0]

        message = _json({
            "goal_id": goal_id,
            "goal_job_key": key,
            "criterion_id": criterion_id,
            "stage": job["stage"],
            "instruction": job["instruction"],
            "allowed_paths": paths,
            "depends_on": job.get("depends_on", []),
        })
        cursor = conn.execute(
            "INSERT INTO jobs(user_id,job_type,source,parent_job_id,message,status,max_retries) "
            "SELECT user_id,'goal_child','goal_ai',?,?, 'pending', 2 FROM goal_chains WHERE goal_id=?",
            (parent_job_id, message, goal_id),
        )
        job_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO goal_chain_jobs(goal_id,goal_job_key,criterion_id,job_id) VALUES(?,?,?,?)",
            (goal_id, key, criterion_id, job_id),
        )
        return {"job_id": job_id, "status": "pending", "parent_job_id": parent_job_id, "created": True}


def get_goal_job_states(goal_id: str) -> dict[str, str]:
    """Normalize both historical terminal spellings to the planner's vocabulary."""
    init_goal_job_store()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT link.goal_job_key,j.status FROM goal_chain_jobs link "
            "JOIN jobs j ON j.id=link.job_id WHERE link.goal_id=? ORDER BY link.id",
            (goal_id,),
        ).fetchall()
    normalized = {}
    for key, status in rows:
        if status in {"done", "completed"}:
            normalized[key] = "done"
        elif status in {"pending", "running", "failed", "held"}:
            normalized[key] = status
        else:
            normalized[key] = "held"
    return normalized


def update_goal_evidence(goal_id: str, criterion_results: object) -> dict[str, Any]:
    """Store explicit evidence states; all criteria must PASS to close a Goal."""
    if not isinstance(criterion_results, dict) or not criterion_results:
        raise ValueError("criterion_results must be a non-empty object")
    if any(not isinstance(value, str) or value not in _ALLOWED_STATES for value in criterion_results.values()):
        raise ValueError("criterion evidence state is invalid")
    init_goal_job_store()
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT goal_json,status FROM goal_chains WHERE goal_id=?", (goal_id,)).fetchone()
        if row is None:
            raise ValueError("goal not found")
        goal = json.loads(row[0])
        expected = {item.get("id") for item in goal["success_criteria"] if isinstance(item, dict)}
        if set(criterion_results) != expected:
            raise ValueError("criterion evidence must cover every registered criterion")
        status = "achieved" if all(value == "PASS" for value in criterion_results.values()) else "active"
        conn.execute(
            "UPDATE goal_chains SET evidence_json=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE goal_id=?",
            (_json(criterion_results), status, goal_id),
        )
    return get_goal(goal_id)



def complete_claimed_child_job(
    job_id: int,
    claim_token: str,
    *,
    success: bool,
    result: str | None = None,
    last_error: str | None = None,
    evidence: object = None,
) -> bool:
    """Atomically complete a typed child JOB and attach evidence to its Goal link."""
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise ValueError("job_id is invalid")
    if not isinstance(claim_token, str) or not claim_token.strip():
        raise ValueError("claim_token is required")
    if not isinstance(success, bool):
        raise ValueError("success must be boolean")
    evidence_json = None
    if success:
        if not isinstance(evidence, dict) or not isinstance(evidence.get("checks"), list) or not evidence["checks"]:
            raise ValueError("successful completion requires non-empty evidence checks")
        for check in evidence["checks"]:
            if (
                not isinstance(check, dict)
                or not isinstance(check.get("name"), str) or not check["name"].strip()
                or not isinstance(check.get("status"), str) or check.get("status") not in {"PASS", "FAIL"}
                or not isinstance(check.get("source"), str) or not check["source"].strip()
            ):
                raise ValueError("evidence checks require name, PASS/FAIL status, and source")
        evidence_json = _json(evidence)
    init_goal_job_store()
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE jobs SET status=?,result=?,last_error=?,claim_token=NULL,updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND job_type='goal_child' AND status='running' AND claim_token=?",
            ("completed" if success else "failed", result, last_error, job_id, claim_token),
        )
        if cursor.rowcount != 1:
            return False
        if success:
            link = conn.execute(
                "UPDATE goal_chain_jobs SET evidence_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                (evidence_json, job_id),
            )
            if link.rowcount != 1:
                raise ValueError("Goal child link is missing")
        return True


def authorize_claimed_job(job: object) -> dict[str, Any]:
    """Re-check a claimed typed job against its persisted Goal grant."""
    if not isinstance(job, dict) or job.get("job_type") != "goal_child":
        raise PermissionError("not a Goal child JOB")
    try:
        payload = json.loads(job.get("message", ""))
    except (TypeError, json.JSONDecodeError):
        raise PermissionError("Goal child payload is malformed")
    if not isinstance(payload, dict):
        raise PermissionError("Goal child payload is malformed")
    goal_id = payload.get("goal_id")
    init_goal_job_store()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT grant_json,status FROM goal_chains WHERE goal_id=?",
            (goal_id,),
        ).fetchone()
        link = conn.execute(
            "SELECT goal_job_key FROM goal_chain_jobs WHERE goal_id=? AND job_id=?",
            (goal_id, job.get("id")),
        ).fetchone()
    if row is None or row[1] != "active" or link is None or link[0] != payload.get("goal_job_key"):
        raise PermissionError("Goal child is not registered under an active Goal")
    goal_contract = json.loads(row[2])
    registered_job = next((item for item in goal_contract.get("jobs", [])
                           if isinstance(item, dict) and item.get("id") == payload.get("goal_job_key")), None)
    if not isinstance(registered_job, dict):
        raise PermissionError("claimed child JOB is not in the persisted Goal contract")
    for field in ("criterion_id", "stage", "allowed_paths", "depends_on"):
        default = [] if field == "depends_on" else None
        if registered_job.get(field, default) != payload.get(field, default):
            raise PermissionError("claimed child JOB differs from the persisted Goal contract")
    if registered_job.get("instruction", "").strip() != payload.get("instruction", "").strip():
        raise PermissionError("claimed child JOB instruction differs from the persisted Goal contract")
    grant = _validate_grant(json.loads(row[0]), goal_id)
    decision = evaluate_job_autonomy(payload)
    if (
        decision.get("decision") != "AUTO_APPROVE"
        or payload.get("stage") not in grant["allowed_stages"]
        or any(not any(path.startswith(root) for root in grant["allowed_path_prefixes"])
               for path in payload.get("allowed_paths", []))
    ):
        raise PermissionError("Goal child no longer satisfies the autonomy policy")
    return payload


def save_child_evidence(job_id: int, evidence: object) -> bool:
    """Persist structured executor evidence for an exactly registered child JOB."""
    if not isinstance(evidence, dict) or not isinstance(evidence.get("checks"), list) or not evidence["checks"]:
        raise ValueError("evidence must contain non-empty checks")
    for check in evidence["checks"]:
        if (
            not isinstance(check, dict)
            or not isinstance(check.get("name"), str) or not check["name"].strip()
            or check.get("status") not in {"PASS", "FAIL"}
            or not isinstance(check.get("source"), str) or not check["source"].strip()
        ):
            raise ValueError("each evidence check requires name, PASS/FAIL status, and source")
    init_goal_job_store()
    with db.get_conn() as conn:
        cursor = conn.execute(
            "UPDATE goal_chain_jobs SET evidence_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
            (_json(evidence), job_id),
        )
        return cursor.rowcount == 1


__all__ = [
    "init_goal_job_store", "create_goal", "get_goal", "persist_child_job",
    "get_goal_job_states", "update_goal_evidence", "authorize_claimed_job", "save_child_evidence", "complete_claimed_child_job",
]
