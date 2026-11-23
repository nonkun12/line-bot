"""Connect goal planning to the existing guarded autonomous runtime."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from scripts.autonomous_task_refill import read_json, _validate_task
from scripts.goal_autopilot import evaluate_goal
from scripts.goal_state_store import GoalStateStore

ROOT = Path(__file__).resolve().parents[1]
GOAL_ID = "distributed-loop-main-goal-v1"

def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)

def _authorized_queue(queue_path: Path, catalog_path: Path, completed: set[str]) -> list[dict[str, Any]]:
    queue, catalog = read_json(queue_path), read_json(catalog_path)
    queued, registered = queue.get("tasks"), catalog.get("tasks")
    if not isinstance(queued, list) or not isinstance(registered, list):
        raise ValueError("queue_or_catalog_tasks_invalid")
    by_id = {}
    for raw in registered:
        task = _validate_task(raw)
        if task["id"] in by_id:
            raise ValueError("duplicate_registered_task_id")
        by_id[task["id"]] = task
    result, seen = [], set()
    for raw in queued:
        if not isinstance(raw, dict):
            raise ValueError("runtime_task_invalid")
        task_id = raw.get("id")
        if not isinstance(task_id, str) or task_id in seen:
            raise ValueError("runtime_task_id_invalid_or_duplicate")
        seen.add(task_id)
        trusted = by_id.get(task_id)
        if trusted is None or trusted.get("execution_approved") is not True:
            raise ValueError("runtime_task_not_explicitly_approved")
        if any(raw.get(k) != trusted.get(k) for k in ("id", "instruction", "allowed_paths")):
            raise ValueError("runtime_task_definition_mismatch")
        if task_id in completed:
            continue
        kind = "TEST" if all(p.startswith(("tests/", "uhip/tests/")) for p in trusted["allowed_paths"]) else "CODE_CHANGE"
        result.append({
            "task_id": task_id, "instruction": trusted["instruction"], "status": "PENDING",
            "kind": kind, "execution_authorized": True, "allowed_paths": list(trusted["allowed_paths"]),
            "priority": 0,
        })
    return result

def _load_goal(store: GoalStateStore, state: dict[str, Any], tasks: list[dict[str, Any]], completed: set[str], resume_task_id: str = ""):
    existing = state.get("goal_autopilot")
    if existing is None:
        if not tasks:
            raise LookupError("no_authorized_tasks")
        goal = {
            "goal_id": GOAL_ID,
            "objective": "Complete the versioned, explicitly approved distributed-loop task queue",
            "acceptance_criteria": [{"id": "approved-runtime-queue-complete", "verified": False}],
            "safety_gate": True, "kill_switch": False, "tasks": tasks,
        }
        store.create(goal)
        return store.read(GOAL_ID)
    if not isinstance(existing, dict) or existing.get("goal_id") != GOAL_ID:
        raise ValueError("durable_goal_state_invalid")
    if evaluate_goal(existing)["decision"] == "INVALID":
        raise ValueError("durable_goal_state_invalid")
    store.create(existing)
    loaded = store.read(GOAL_ID)
    assert loaded is not None
    revision, goal = loaded
    by_id = {t["task_id"]: t for t in goal["tasks"]}
    current_ids = {t["task_id"] for t in tasks}
    changed = False
    for old in goal["tasks"]:
        if old["status"] == "PENDING" and old["task_id"] not in current_ids:
            old["status"] = "HELD"
            old["hold_reason"] = "task_missing_from_current_approved_runtime_queue"
            changed = True
        if old["status"] == "PENDING" and old["task_id"] in completed:
            old["status"] = "HELD"
            old["hold_reason"] = "completion_state_missing_goal_evidence"
            changed = True
    for task in tasks:
        old = by_id.get(task["task_id"])
        if old is None:
            goal["tasks"].append(task)
            changed = True
        elif any(old.get(k) != task.get(k) for k in ("instruction", "allowed_paths", "kind", "execution_authorized")):
            if old["status"] == "PENDING":
                old["status"] = "HELD"
                old["hold_reason"] = "registered_task_definition_changed"
                changed = True
    if resume_task_id:
        if resume_task_id not in current_ids:
            raise ValueError("resume_task_not_in_current_approved_queue")
        resume_target = next((t for t in goal["tasks"] if t["task_id"] == resume_task_id), None)
        if resume_target is None:
            raise ValueError("resume_task_missing_from_goal")
        if resume_target["status"] in {"HELD", "FAILED"}:
            resume_target["status"] = "PENDING"
            resume_target.pop("hold_reason", None)
            resume_target["priority"] = max(
                (int(t.get("priority", 0)) for t in goal["tasks"]), default=0
            ) + 1
            changed = True
    if changed:
        for criterion in goal["acceptance_criteria"]:
            criterion["verified"] = False
            criterion.pop("evidence_ref", None)
        store.compare_and_swap(GOAL_ID, revision, goal)
        loaded = store.read(GOAL_ID)
    return loaded

def _valid_success(row: dict[str, Any], task_id: str) -> bool:
    if row.get("task_id") != task_id or row.get("status") not in {"PASS", "NO_CHANGE"} or row.get("exit_code") != 0:
        return False
    for key in ("base_sha", "produced_sha"):
        value = row.get(key)
        if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            return False
    if not isinstance(row.get("run_nonce"), str) or not row["run_nonce"].strip():
        return False
    recovery = row.get("recovery_ai")
    tower = row.get("control_tower")
    orchestration = tower.get("orchestration") if isinstance(tower, dict) else None
    rea_artifact = row.get("rea_artifact")
    if not isinstance(recovery, dict) or recovery.get("recorded") is not True:
        return False
    if not isinstance(orchestration, dict) or orchestration.get("allow_continue") is not True:
        return False
    if not isinstance(rea_artifact, dict) or rea_artifact.get("status") not in {"PASS", "NO_CHANGE"}:
        return False
    try:
        from scripts.rea_control_tower_adapter import publish_row_has_valid_gates
        return publish_row_has_valid_gates(row, expected_sha=row["base_sha"]) is True
    except Exception:
        return False

def _append_blocked(path: Path, task_id: str, reason: str) -> None:
    row = {"timestamp": datetime.now(timezone.utc).isoformat(), "task_id": task_id,
           "status": "BLOCKED", "exit_code": 80, "failure_reason": reason}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

def _reconcile_claimed_tasks(store: GoalStateStore, task_ids: set[str], output: Path,
                            failed_task_id: str | None = None) -> None:
    if not task_ids:
        return
    loaded = store.read(GOAL_ID)
    if loaded is None:
        raise RuntimeError("goal_state_missing_while_reconciling")
    revision, goal = loaded
    for task in goal["tasks"]:
        if task["task_id"] in task_ids:
            task.pop("completion_evidence", None)
            if task["task_id"] == failed_task_id:
                task["status"] = "HELD"
                task["hold_reason"] = "guarded_runtime_or_evidence_gate_failed"
            else:
                # Earlier tasks in this un-published workflow are not complete
                # in durable state; leave them pending for a later safe cycle.
                task["status"] = "PENDING"
                task.pop("hold_reason", None)
    for criterion in goal["acceptance_criteria"]:
        criterion["verified"] = False
        criterion.pop("evidence_ref", None)
    store.compare_and_swap(GOAL_ID, revision, goal)
    latest = store.read(GOAL_ID)
    if latest is None:
        raise RuntimeError("goal_state_missing_after_reconciliation")
    _write_state(output, latest[1])


def run(args: argparse.Namespace) -> int:
    queue_path = Path(os.environ.get("AUTONOMOUS_LOOP_TASK_QUEUE", ".github/autonomous-loop-tasks.json"))
    state_path, results_path, stop_file = args.state.resolve(), args.results.resolve(), args.stop_file.resolve()
    goal_output = args.goal_state_output.resolve()
    goal_output.unlink(missing_ok=True)
    state = read_json(state_path)
    done = state.get("completed", [])
    if not isinstance(done, list) or not all(isinstance(x, str) for x in done):
        raise ValueError("durable_completed_state_invalid")
    completed = set(done)
    authorized = _authorized_queue(queue_path, args.catalog, completed)
    if not authorized:
        return 78
    with tempfile.TemporaryDirectory(prefix="goal-autopilot-") as tmp:
        store = GoalStateStore(Path(tmp) / "goal.sqlite3")
        claimed_this_run: set[str] = set()
        loaded = _load_goal(store, state, authorized, completed, os.environ.get("GOAL_RESUME_TASK_ID", "").strip())
        if loaded is None:
            raise RuntimeError("goal_state_missing")
        _, goal = loaded
        for _ in range(args.max_tasks):
            if stop_file.exists():
                if claimed_this_run:
                    _reconcile_claimed_tasks(store, claimed_this_run, goal_output)
                    return 80
                return 79
            claim = store.claim_next(GOAL_ID)
            if claim.get("decision") == "COMPLETE":
                break
            if claim.get("decision") != "CLAIMED":
                if claimed_this_run:
                    _reconcile_claimed_tasks(store, claimed_this_run, goal_output)
                    return 80
                return 79
            claimed_this_run.add(str(claim["task_id"]))
            loaded = store.read(GOAL_ID)
            if loaded is None:
                raise RuntimeError("goal_state_disappeared_after_claim")
            _, claimed_goal = loaded
            selected = next(t for t in authorized if t["task_id"] == claim["task_id"])
            one_queue = {"version": 1, "max_tasks_per_run": 1, "tasks": [{
                "id": selected["task_id"], "instruction": selected["instruction"],
                "allowed_paths": selected["allowed_paths"],
            }]}
            with tempfile.TemporaryDirectory(prefix="goal-runtime-queue-") as queue_tmp:
                child_queue = Path(queue_tmp) / "queue.json"
                child_queue.write_text(json.dumps(one_queue, ensure_ascii=False) + "\n", encoding="utf-8")
                env = os.environ.copy()
                env["AUTONOMOUS_LOOP_TASK_QUEUE"] = str(child_queue)
                before = len(results_path.read_text(encoding="utf-8").splitlines()) if results_path.exists() else 0
                command = [sys.executable, "scripts/run_minimal_autonomous_loop.py",
                           "--max-tasks", "1", "--stop-file", str(stop_file),
                           "--state", str(state_path), "--results", str(results_path)]
                child = subprocess.run(command, cwd=ROOT, env=env, check=False)
            lines = results_path.read_text(encoding="utf-8").splitlines() if results_path.exists() else []
            rows = []
            for line in lines[before:]:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        rows.append(value)
                except ValueError:
                    continue
            matching = [r for r in rows if r.get("task_id") == selected["task_id"]]
            row = matching[-1] if len(rows) == 1 and len(matching) == 1 else None
            if row is not None and child.returncode == 0 and _valid_success(row, selected["task_id"]):
                digest = hashlib.sha1(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                store.record_result(GOAL_ID, selected["task_id"], status="COMPLETED",
                    completion_evidence={"task_id": selected["task_id"], "verified": True,
                        "evidence_sha": digest, "verification_ref": "run:" + row["run_nonce"],
                        "completed_at": datetime.now(timezone.utc).isoformat()})
                completed.add(selected["task_id"])
                state["completed"] = sorted(completed)
                latest = store.read(GOAL_ID)
                assert latest is not None
                rev, updated = latest
                if all(t["status"] == "COMPLETED" for t in updated["tasks"]):
                    criterion = updated["acceptance_criteria"][0]
                    criterion["verified"] = True
                    criterion["evidence_ref"] = "commit:" + row["produced_sha"]
                    store.compare_and_swap(GOAL_ID, rev, updated)
                _write_state(state_path, state)
                if child.returncode != 0:
                    return child.returncode
            else:
                # Runner sentinels 78/79 mean the guarded child did not execute
                # this task (queue exhaustion or an upstream HOLD/STOP gate).
                # Preserve the sentinel and return the claim to PENDING: marking
                # it HELD here would create a second, stale GoalAutopilot hold
                # that survives after the upstream gate is independently reviewed.
                # This does not clear or bypass Recovery AI / STOP / approval gates.
                if child.returncode in {78, 79}:
                    _reconcile_claimed_tasks(store, claimed_this_run, goal_output)
                    return child.returncode
                store.record_result(GOAL_ID, selected["task_id"], status="HELD")
                _reconcile_claimed_tasks(store, claimed_this_run, goal_output, selected["task_id"])
                if row is None:
                    _append_blocked(results_path, selected["task_id"], "goal_runtime_result_missing_or_ambiguous")
                elif child.returncode == 0:
                    _append_blocked(results_path, selected["task_id"], "goal_runtime_independent_evidence_gate_failed")
                return child.returncode or 80
        latest = store.read(GOAL_ID)
        if latest:
            _write_state(goal_output, latest[1])
    return 0

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--goal-state-output", type=Path, required=True)
    parser.add_argument("--max-tasks", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.max_tasks <= 4:
        raise SystemExit("--max-tasks must be between 1 and 4")
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("GOAL_AUTOPILOT=BLOCKED reason=" + type(exc).__name__, flush=True)
        return 80

if __name__ == "__main__":
    raise SystemExit(main())
