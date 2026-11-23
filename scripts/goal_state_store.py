"""Atomic SQLite persistence for the goal autopilot single-task lifecycle."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any
from scripts.goal_autopilot import _valid_completion_evidence, evaluate_goal

class GoalStateStore:
    """Durable CAS state. Claims work but deliberately never executes it."""
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:": Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS goal_state (goal_id TEXT PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision >= 0), document TEXT NOT NULL)""")
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn
    def create(self, goal: dict[str, Any]) -> int:
        decision = evaluate_goal(goal)
        if decision["decision"] == "INVALID": raise ValueError("goal is not eligible for durable registration")
        payload = json.dumps(goal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("INSERT INTO goal_state VALUES (?, 0, ?)", (goal["goal_id"], payload)); conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback(); raise ValueError("goal already exists") from exc
        return 0
    def read(self, goal_id: str):
        with self._connect() as conn: row = conn.execute("SELECT revision, document FROM goal_state WHERE goal_id=?", (goal_id,)).fetchone()
        if row is None: return None
        value = json.loads(row["document"])
        if not isinstance(value, dict) or value.get("goal_id") != goal_id: raise ValueError("durable goal document is corrupt")
        return int(row["revision"]), value
    def compare_and_swap(self, goal_id: str, expected_revision: int, goal: dict[str, Any]) -> int:
        if type(expected_revision) is not int or expected_revision < 0: raise ValueError("invalid expected revision")
        if goal.get("goal_id") != goal_id: raise ValueError("goal ID cannot change")
        if evaluate_goal(goal)["decision"] == "INVALID": raise ValueError("invalid goal state")
        payload = json.dumps(goal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("UPDATE goal_state SET revision=revision+1, document=? WHERE goal_id=? AND revision=?", (payload, goal_id, expected_revision))
            if cur.rowcount != 1: conn.rollback(); raise RuntimeError("goal revision conflict")
            conn.commit()
        return expected_revision + 1
    def claim_next(self, goal_id: str) -> dict[str, Any]:
        """Atomically persist IN_PROGRESS before any external executor can run."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT revision, document FROM goal_state WHERE goal_id=?", (goal_id,)).fetchone()
            if row is None: conn.rollback(); return {"decision":"HOLD","reason":"goal_not_found"}
            revision, goal = int(row["revision"]), json.loads(row["document"])
            decision = evaluate_goal(goal)
            if decision["decision"] != "CONTINUE": conn.rollback(); return decision
            task = next(item for item in goal["tasks"] if item["task_id"] == decision["task_id"])
            task["status"] = "IN_PROGRESS"
            payload = json.dumps(goal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            cur = conn.execute("UPDATE goal_state SET revision=revision+1, document=? WHERE goal_id=? AND revision=?", (payload, goal_id, revision))
            if cur.rowcount != 1: conn.rollback(); return {"decision":"HOLD","reason":"goal_revision_conflict"}
            conn.commit()
            return {**decision, "decision":"CLAIMED", "revision":revision+1}
    def record_result(self, goal_id: str, task_id: str, *, status: str, completion_evidence: dict[str, Any] | None = None, failure_evidence: dict[str, Any] | None = None) -> int:
        if status not in {"COMPLETED","FAILED","HELD"}: raise ValueError("unsupported terminal task status")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT revision, document FROM goal_state WHERE goal_id=?", (goal_id,)).fetchone()
            if row is None: conn.rollback(); raise KeyError("goal not found")
            revision, goal = int(row["revision"]), json.loads(row["document"])
            task = next((item for item in goal["tasks"] if item.get("task_id") == task_id), None)
            if task is None or task.get("status") != "IN_PROGRESS": conn.rollback(); raise RuntimeError("task is not the active claimed task")
            if status == "COMPLETED":
                task["completion_evidence"] = completion_evidence
                if not _valid_completion_evidence(task): conn.rollback(); raise ValueError("verified task-bound completion evidence required")
                task.pop("failure_evidence", None)
            elif failure_evidence is not None:
                allowed_stages = {"child_runner", "result_collection", "independent_evidence"}
                allowed_reasons = {
                    "runner_nonzero_exit", "guarded_runner_sentinel",
                    "result_missing_or_ambiguous", "success_evidence_rejected",
                }
                if (not isinstance(failure_evidence, dict)
                        or failure_evidence.get("stage") not in allowed_stages
                        or failure_evidence.get("reason_code") not in allowed_reasons
                        or set(failure_evidence) - {"stage", "reason_code", "child_exit_code", "result_status", "result_exit_code"}):
                    conn.rollback(); raise ValueError("failure evidence schema invalid")
                for key in ("child_exit_code", "result_exit_code"):
                    if key in failure_evidence and (type(failure_evidence[key]) is not int or not -255 <= failure_evidence[key] <= 255):
                        conn.rollback(); raise ValueError("failure evidence exit code invalid")
                if "result_status" in failure_evidence and failure_evidence["result_status"] not in {"PASS", "NO_CHANGE", "FAIL", "BLOCKED", "NOT_RUN", "INCOMPLETE"}:
                    conn.rollback(); raise ValueError("failure evidence result status invalid")
                task["failure_evidence"] = dict(failure_evidence)
            task["status"] = status
            payload = json.dumps(goal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            cur = conn.execute("UPDATE goal_state SET revision=revision+1, document=? WHERE goal_id=? AND revision=?", (payload, goal_id, revision))
            if cur.rowcount != 1: conn.rollback(); raise RuntimeError("goal revision conflict")
            conn.commit()
        return revision + 1
