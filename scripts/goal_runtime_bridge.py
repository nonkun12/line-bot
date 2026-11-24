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
    """Build a run-scoped goal without mutating unrelated durable HOLD state.

    Global safety controls and unresolved in-flight work remain authoritative.
    Existing HELD/FAILED tasks stay held; they only block a candidate with the
    same ID. The transient goal is never written back as the durable main goal.
    """
    existing = state.get("goal_autopilot")
    if existing is None:
        safety_gate, kill_switch = True, False
        existing_by_id = {}
    else:
        if not isinstance(existing, dict) or existing.get("goal_id") != GOAL_ID:
            raise ValueError("durable_goal_state_invalid")
        if evaluate_goal(existing)["decision"] == "INVALID":
            raise ValueError("durable_goal_state_invalid")
        safety_gate = existing.get("safety_gate")
        kill_switch = existing.get("kill_switch")
        existing_tasks = existing.get("tasks", [])
        if not isinstance(existing_tasks, list):
            raise ValueError("durable_goal_tasks_invalid")
        existing_by_id = {
            item.get("task_id"): item for item in existing_tasks
            if isinstance(item, dict) and isinstance(item.get("task_id"), str)
        }
        if any(item.get("status") == "IN_PROGRESS" for item in existing_tasks if isinstance(item, dict)):
            raise ValueError("in_flight_task_requires_reconciliation")
        completed_goal_ids = {
            item["task_id"] for item in existing_tasks
            if isinstance(item, dict) and item.get("status") == "COMPLETED"
        }
        if not completed_goal_ids.issubset(completed):
            raise ValueError("completed_goal_task_missing_durable_completion")
    if safety_gate is not True or kill_switch is not False:
        raise ValueError("global_goal_safety_gate_blocked")
    current_ids = {task["task_id"] for task in tasks}
    if resume_task_id and resume_task_id not in current_ids:
        raise ValueError("resume_task_not_in_current_approved_queue")
    scoped_tasks = []
    for task in tasks:
        prior = existing_by_id.get(task["task_id"])
        if prior is not None and prior.get("status") in {"HELD", "FAILED"}:
            if resume_task_id != task["task_id"]:
                raise ValueError("candidate_task_requires_human_review")
            task = dict(task)
            task["priority"] = max(
                (int(item.get("priority", 0)) for item in existing_by_id.values()
                 if type(item.get("priority", 0)) is int), default=0
            ) + 1
        if prior is not None and prior.get("status") == "IN_PROGRESS":
            raise ValueError("candidate_task_in_flight_requires_reconciliation")
        scoped_tasks.append(task)
    if not scoped_tasks:
        raise LookupError("no_authorized_tasks")
    goal = {
        "goal_id": GOAL_ID,
        "objective": "Execute only the current explicitly approved bounded runtime queue",
        "acceptance_criteria": [{"id": "approved-runtime-queue-complete", "verified": False}],
        "safety_gate": safety_gate, "kill_switch": kill_switch, "tasks": scoped_tasks,
    }
    store.create(goal)
    return store.read(GOAL_ID)

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

def _record_preflight_rea(path: Path, expected_sha: str) -> None:
    """Persist bounded, read-only REA evidence before GoalAutopilot can return HOLD."""
    valid_sha = (
        isinstance(expected_sha, str)
        and len(expected_sha) == 40
        and all(char in "0123456789abcdef" for char in expected_sha)
    )
    evidence: dict[str, Any]
    try:
        from scripts.rea_control_tower_adapter import prepare_rea_evidence

        evidence = prepare_rea_evidence(ROOT, expected_sha=expected_sha)
        if not isinstance(evidence, dict):
            evidence = {"gate": "BLOCKED", "reason_code": "rea_report_invalid"}
    except Exception:
        # Do not leak exception text, filesystem paths, or environment details.
        evidence = {"gate": "BLOCKED", "reason_code": "rea_preflight_failed"}

    gate = evidence.get("gate")
    if (
        gate not in {"PASS", "BLOCKED"}
        or not valid_sha
        or (gate == "PASS" and evidence.get("target_sha") != expected_sha)
    ):
        gate = "BLOCKED"
    reason = evidence.get("reason_code")
    if not isinstance(reason, str) or not reason or len(reason) > 80 or not reason.replace("_", "").isalnum():
        reason = "rea_preflight_blocked" if gate == "BLOCKED" else None
    scanner_status = evidence.get("scanner_status")
    scanner_status_valid = scanner_status in {"PASS", "FINDINGS"}
    if not scanner_status_valid:
        scanner_status = "BLOCKED"
    finding_count = evidence.get("finding_count")
    blocking_count = evidence.get("blocking_count")
    counts_valid = (
        type(finding_count) is int and 0 <= finding_count <= 10000
        and type(blocking_count) is int and 0 <= blocking_count <= 10000
        and blocking_count <= finding_count
    )
    if not counts_valid:
        finding_count = 0
        blocking_count = 0
    if (
        not scanner_status_valid
        or not counts_valid
        or (scanner_status == "PASS" and finding_count != 0)
        or (scanner_status == "FINDINGS" and finding_count == 0)
        or blocking_count
    ):
        gate = "BLOCKED"
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": "pre_execution",
        "target_sha": expected_sha if valid_sha else None,
        "gate": gate,
        "reason_code": reason if gate == "BLOCKED" else None,
        "scanner_status": scanner_status,
        "finding_count": finding_count,
        "blocking_count": blocking_count,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    row["evidence_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"REA_PREFLIGHT={gate} reason={row['reason_code'] or 'none'}", flush=True)
    except Exception:
        # A failed persistence attempt cannot grant permission or clear HOLD.
        print("REA_PREFLIGHT=BLOCKED reason=rea_preflight_record_failed", flush=True)


def _valid_no_execution_block(row: dict[str, Any] | None, task_id: str, child_returncode: int) -> bool:
    """Accept only an identity-bound guarded gate denial."""
    if not isinstance(row, dict) or child_returncode not in {80, 81, 82}:
        return False
    evidence = row.get("gate_evidence")
    expected_gate = {80: "rea", 81: "execution_approval", 82: "emergency_stop"}[child_returncode]
    base_sha, produced_sha, nonce = row.get("base_sha"), row.get("produced_sha"), row.get("run_nonce")
    return bool(
        row.get("task_id") == task_id and row.get("status") == "BLOCKED"
        and row.get("exit_code") == child_returncode
        and isinstance(base_sha, str) and len(base_sha) == 40
        and all(ch in "0123456789abcdef" for ch in base_sha)
        and produced_sha == base_sha
        and isinstance(nonce, str) and len(nonce) == 32
        and all(ch in "0123456789abcdef" for ch in nonce)
        and isinstance(evidence, dict) and evidence.get("gate") == "BLOCKED"
        and evidence.get("gate_name") == expected_gate
        and evidence.get("exit_code") == child_returncode
        and isinstance(evidence.get("reason_code"), str) and bool(evidence.get("reason_code").strip())
        and all(evidence.get(key) is False for key in (
            "execution_authorized", "patch_authorized", "hold_clear_authorized", "merge_deploy_authorized"
        ))
    )


def _failure_evidence(child_returncode: int, row: dict[str, Any] | None) -> dict[str, Any]:
    """Persist only bounded, allowlisted failure metadata; never copy raw logs."""
    if row is None:
        if child_returncode in {78, 79}:
            return {
                "stage": "child_runner",
                "reason_code": "guarded_runner_sentinel",
                "child_exit_code": child_returncode,
            }
        return {
            "stage": "result_collection",
            "reason_code": "result_missing_or_ambiguous",
            "child_exit_code": child_returncode,
        }
    row_status = row.get("status")
    safe_status = row_status if isinstance(row_status, str) and row_status in {
        "PASS", "NO_CHANGE", "FAIL", "BLOCKED", "NOT_RUN", "INCOMPLETE"
    } else "NOT_RUN"
    result: dict[str, Any] = {
        "child_exit_code": child_returncode,
        "result_status": safe_status,
    }
    row_exit = row.get("exit_code")
    if type(row_exit) is int and -255 <= row_exit <= 255:
        result["result_exit_code"] = row_exit
    if child_returncode in {78, 79}:
        result.update(stage="child_runner", reason_code="guarded_runner_sentinel")
    elif child_returncode != 0:
        result.update(stage="child_runner", reason_code="runner_nonzero_exit")
    else:
        result.update(stage="independent_evidence", reason_code="success_evidence_rejected")
    return result

def _append_hold_diagnostic(path: Path, decision: dict[str, Any], goal: dict[str, Any]) -> None:
    """Persist bounded pre-execution HOLD evidence for REA; never changes authorization."""
    raw_tasks = goal.get("tasks", [])
    tasks = raw_tasks if isinstance(raw_tasks, list) else []
    counts: dict[str, int] = {}
    blocked_tasks: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = task.get("status")
        if isinstance(status, str):
            counts[status] = counts.get(status, 0) + 1
        if status not in {"HELD", "FAILED", "IN_PROGRESS"}:
            continue
        item: dict[str, Any] = {}
        for key in ("task_id", "status"):
            value = task.get(key)
            if isinstance(value, str) and value:
                item[key] = value[:120]
        reason = task.get("hold_reason")
        if isinstance(reason, str) and reason and len(reason) <= 100 and reason.replace("_", "").replace("-", "").isalnum():
            item["hold_reason"] = reason
        evidence = task.get("failure_evidence")
        if isinstance(evidence, dict):
            safe_evidence: dict[str, Any] = {}
            for key in ("stage", "reason_code", "result_status"):
                value = evidence.get(key)
                if isinstance(value, str) and len(value) <= 80 and value.replace("_", "").replace("-", "").isalnum():
                    safe_evidence[key] = value
            for key in ("child_exit_code", "result_exit_code"):
                value = evidence.get(key)
                if type(value) is int and -255 <= value <= 255:
                    safe_evidence[key] = value
            if safe_evidence:
                item["failure_evidence"] = safe_evidence
        if item:
            blocked_tasks.append(item)
    reason = decision.get("reason")
    if not isinstance(reason, str) or not reason:
        reason = "failed_or_held_task_requires_review" if blocked_tasks else "unclassified_goal_decision"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": "pre_execution",
        "decision": decision.get("decision") if decision.get("decision") in {"HOLD", "INVALID", "COMPLETE"} else "HOLD",
        "reason": reason if isinstance(reason, str) and len(reason) <= 100 and reason.replace("_", "").replace("-", "").isalnum() else "unclassified_goal_decision",
        "task_id": decision.get("task_id") if isinstance(decision.get("task_id"), str) else None,
        "task_ids": decision.get("task_ids") if isinstance(decision.get("task_ids"), list) and all(isinstance(x, str) for x in decision["task_ids"]) else [],
        "task_counts": counts,
        "blocked_tasks": blocked_tasks[:50],
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


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
    rea_path = Path(os.environ.get(
        "REA_PREFLIGHT_EVIDENCE_PATH",
        str(results_path.with_name("rea-preflight-evaluations.jsonl")),
    ))
    _record_preflight_rea(rea_path, os.environ.get("GITHUB_SHA", ""))
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
                diagnostics_path = Path(os.environ.get(
                    "GOAL_AUTOPILOT_DIAGNOSTICS_PATH",
                    str(goal_output.with_name("goal-autopilot-hold-evaluations.jsonl")),
                ))
                _append_hold_diagnostic(diagnostics_path, claim, goal)
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
                if _valid_no_execution_block(row, selected["task_id"], child.returncode):
                    _reconcile_claimed_tasks(store, claimed_this_run, goal_output)
                    return 0
                failure_evidence = _failure_evidence(child.returncode, row)
                store.record_result(
                    GOAL_ID, selected["task_id"], status="HELD",
                    failure_evidence=failure_evidence,
                )
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
