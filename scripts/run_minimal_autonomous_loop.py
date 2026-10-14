"""Minimal, fail-closed autonomous development loop.

This MVP executes at most one queued task by default. A later task is reached
only when the previous guarded runtime returns success. No merge/deploy is
performed here. A kill-switch file or environment variable stops before the
next task.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Running this file as `python scripts/run_minimal_autonomous_loop.py` puts
# scripts/ (not the repository root) at sys.path[0]. Add ROOT explicitly so
# fail-closed Recovery AI imports work in GitHub Actions and local invocations.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
QUEUE = ROOT / ".github" / "autonomous-loop-tasks.json"
DEFAULT_STOP_FILE = Path("/tmp/line-bot-autonomous-loop.stop")
ACTIVE_PROCESS: subprocess.Popen[str] | None = None
ACTIVE_RESUME_CONTEXT = None

EXIT_NOT_RUN = 78
NOT_RUN_REASON_QUEUE_EMPTY = "queue_empty"
VALID_RUNTIME_STATUSES = frozenset({"PASS", "NO_CHANGE"})

def classify_final_outcome(
    task_statuses: list[str],
    *,
    loop_outcome: str,
    publish_outcome: str,
    state_outcome: str,
    sheets_outcome: str,
    recovery_outcome: str | None = None,
    queue_empty: bool = False,
    all_tasks_held: bool = False,
    requested_tasks: int | None = None,
    queue_completed: int | None = None,
    queue_total: int | None = None,
) -> tuple[str, str]:
    """Fail closed when task evidence, requested work, or a post-run gate is missing."""
    successful = {"PASS", "NO_CHANGE"}
    if queue_empty:
        if task_statuses != ["NOT_RUN"] or loop_outcome != "success":
            return "BLOCKED", "queue_empty_evidence_mismatch"
        failed_gates = [
            name for name, outcome in (
                ("publish", publish_outcome),
                ("state", state_outcome),
                ("sheets", sheets_outcome),
            )
            if outcome != "success"
        ]
        if failed_gates:
            return "BLOCKED", "queue_empty_post_run_gate_failed:" + ",".join(failed_gates)
        return "NOT_RUN", "queue_empty"

    if all_tasks_held:
        if task_statuses != ["BLOCKED"] or loop_outcome != "success":
            return "BLOCKED", "held_queue_evidence_mismatch"
        failed_gates = [
            name for name, outcome in (
                ("publish", publish_outcome),
                ("state", state_outcome),
                ("sheets", sheets_outcome),
            )
            if outcome != "success"
        ]
        if failed_gates:
            return "BLOCKED", "held_queue_post_run_gate_failed:" + ",".join(failed_gates)
        return "BLOCKED", "all_pending_tasks_held"

    if not task_statuses:
        return "BLOCKED", "missing_task_evidence"
    invalid = [status for status in task_statuses if status not in successful]
    if invalid:
        return "FAILED", "task_status:" + ",".join(invalid)

    gate_outcomes = [
        ("loop", loop_outcome),
        ("publish", publish_outcome),
        ("state", state_outcome),
        ("sheets", sheets_outcome),
    ]
    if recovery_outcome is not None:
        gate_outcomes.append(("recovery_ai_persistence", recovery_outcome))
    failed_gates = [
        name for name, outcome in gate_outcomes
        if outcome != "success"
    ]
    if failed_gates:
        return "FAILED", "post_run_gate_failed:" + ",".join(failed_gates)

    if requested_tasks is not None and queue_completed is not None and queue_total is not None:
        if len(task_statuses) < requested_tasks and queue_completed < queue_total:
            return "INCOMPLETE", "requested_task_limit_not_met"
    return "COMPLETED", "required_gates_passed"


INCIDENT_CATEGORIES = frozenset({"local_job_failed", "vault_write_failed"})
INCIDENT_DETAILS = frozenset({
    "OSError", "PermissionError", "FileNotFoundError", "IsADirectoryError",
    "NotADirectoryError", "RuntimeError", "ValueError", "TypeError", "KeyError",
    "AttributeError", "UnicodeDecodeError",
})
INCIDENT_SOURCE_PATHS = [
    "core/obsidian_bridge.py",
    "obsidian_loop_dispatch.py",
    "routes/obsidian_bridge.py",
    "scripts/obsidian_mac_bridge.py",
    "scripts/obsidian_mac_startup.py",
]
INCIDENT_TEST_PATHS = [
    "tests/test_obsidian_autorepair_dispatch.py",
    "tests/test_obsidian_mac_bridge.py",
    "tests/test_obsidian_mac_startup.py",
]


def incident_tasks(category: str, detail: str, job_id: str | None) -> list[dict[str, object]]:
    """Build two bounded repair/test tasks from an allowlisted incident taxonomy."""
    if category not in INCIDENT_CATEGORIES or detail not in INCIDENT_DETAILS:
        raise ValueError("incident category/detail is not allowlisted")
    if job_id is not None:
        if not isinstance(job_id, str) or not job_id.isascii() or not job_id.isdigit():
            raise ValueError("incident job ID is invalid")
        if not 1 <= int(job_id) <= 2**31 - 1 or len(job_id) > 10:
            raise ValueError("incident job ID is out of range")

    job_label = job_id if job_id is not None else "not-provided"
    context = f"Sanitized incident: category={category}, exception_class={detail}, job_id={job_label}."
    source_instruction = (
        f"{context} Investigate the Obsidian bridge implementation and tests in this repository. "
        "This is the source-repair stage. Identify one reproducible defect that plausibly matches "
        "the category and exception class, then make the smallest source-only correction if justified. "
        "If evidence instead indicates a normal user-input rejection, vault permission/configuration "
        "problem, or no code defect, make no source change. Never weaken path validation, approval, "
        "overwrite protection, authentication, kill switches, or fail-closed behavior. "
        "Do not access vault contents, secrets, production services, external APIs/websites, camera, "
        "or OS UI. Do not edit workflow/config/secret/control-plane files and do not merge/deploy. "
        "One source file maximum; run the available automated tests and report evidence."
    )
    test_instruction = (
        f"{context} This is the regression-test stage following the guarded source review. "
        "Add or strengthen exactly one focused test proving the source behavior for the indicated "
        "category/exception class, using dummy data only. Never make the test pass by weakening a guard. "
        "Do not access vault contents, secrets, production services, external APIs/websites, camera, "
        "or OS UI. Do not edit workflow/config/secret/control-plane files and do not merge/deploy. "
        "One test file maximum; run the available automated tests and report evidence."
    )
    suffix = f"{category}-{detail.lower()}"
    return [
        {
            "id": f"obsidian-bridge-fix-{suffix}",
            "instruction": source_instruction,
            "allowed_paths": INCIDENT_SOURCE_PATHS,
        },
        {
            "id": f"obsidian-bridge-regression-{suffix}",
            "instruction": test_instruction,
            "allowed_paths": INCIDENT_TEST_PATHS,
        },
    ]


def load_tasks() -> list[dict[str, object]]:
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError("task queue must contain a list")
    result = []
    for task in tasks:
        if not isinstance(task, dict) or not task.get("id") or not task.get("instruction"):
            raise ValueError("each task needs id and instruction")
        allowed_paths = task.get("allowed_paths")
        if not isinstance(allowed_paths, list) or not allowed_paths or not all(isinstance(path, str) and path.strip() for path in allowed_paths):
            raise ValueError("each task needs non-empty allowed_paths")
        result.append({
            "id": str(task["id"]),
            "instruction": str(task["instruction"]),
            "allowed_paths": [path.strip() for path in allowed_paths],
        })
    return result


def load_completed(state_file: Path) -> set[str]:
    if not state_file.exists():
        return set()
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("autonomous loop state is invalid")
    completed = data.get("completed", [])
    if not isinstance(completed, list) or not all(isinstance(item, str) and item.strip() for item in completed):
        raise ValueError("autonomous loop state completed must be a string list")
    return {item.strip() for item in completed}


def stopped(stop_file: Path) -> bool:
    raw = os.environ.get("AUTONOMOUS_LOOP_STOP", "").strip()
    if raw and raw.casefold() not in {"0", "false", "no", "off"}:
        return True
    try:
        return stop_file.exists()
    except OSError:
        return True


def _valid_sha(value: object) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(ch in "0123456789abcdef" for ch in text.lower())


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _git_checked(*args: str) -> tuple[int, str]:
    completed = subprocess.run(("git", "-C", str(ROOT), *args), capture_output=True, text=True, timeout=15)
    return completed.returncode, completed.stdout.strip()


def _verify_produced_head(base_sha: str, produced_sha: str, allowed_paths: list[str]) -> tuple[bool, str]:
    if not _valid_sha(base_sha) or not _valid_sha(produced_sha):
        return False, "sha_invalid"
    if _git_head() != produced_sha:
        return False, "produced_sha_head_mismatch"
    code, _ = _git_checked("merge-base", "--is-ancestor", base_sha, produced_sha)
    if code != 0:
        return False, "produced_not_descendant_of_base"
    code, diff = _git_checked("diff", "--name-only", base_sha, produced_sha)
    if code != 0:
        return False, "diff_unavailable"
    allowed = {str(path).strip().replace("\\", "/").lstrip("./") for path in allowed_paths}
    if not allowed or any(path.startswith("/") or path == ".." or path.startswith("../") for path in allowed):
        return False, "allowed_paths_invalid"
    changed = {line.strip() for line in diff.splitlines() if line.strip()}
    if not all(any(path == target or path.startswith(target.rstrip("/") + "/") for target in allowed) for path in changed):
        return False, "diff_outside_allowed_paths"
    return True, ""


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    # Do not rely on the leader still being alive: descendants may remain.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _deterministic_target_for_task(task: dict[str, object]) -> str | None:
    """Resolve only queue tasks whose ID and allowed path match the runtime policy."""
    task_id = str(task.get("id", "")).strip()
    allowed_paths = task.get("allowed_paths")
    if not task_id or not isinstance(allowed_paths, list):
        return None
    # A directly launched script can have scripts/ at sys.path[0], without the
    # repository root being importable. Add the known project root explicitly.
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    # Import lazily to keep queue/state inspection lightweight.
    from core.line_development_runtime import _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS

    expected_target = _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS.get(task_id)
    if expected_target is None or allowed_paths != [expected_target]:
        return None
    return expected_target


def run_task(task: dict[str, object], run_index: int, stop_file: Path, summary_dir: Path = Path("/tmp")) -> dict[str, object]:
    summary = summary_dir / f"minimal-autonomous-{task['id']}.json"
    run_nonce = uuid.uuid4().hex
    start_time = datetime.now(timezone.utc)
    base_sha = _git_head()
    env = os.environ.copy()
    if _deterministic_target_for_task(task) is not None:
        # Do not expose provider credentials to deterministic test-only tasks.
        for key in (
            "GROQ_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "OPENROUTER_API_KEY",
            "DEEPSEEK_API_KEY",
            "MISTRAL_API_KEY",
            "COHERE_API_KEY",
        ):
            env.pop(key, None)
    env["DEV_INSTRUCTION"] = task["instruction"]
    env["AUTONOMOUS_SUMMARY_PATH"] = str(summary)
    env["AUTONOMOUS_RUN_SOURCE"] = "minimal-mvp-loop"
    env["AUTONOMOUS_TASK_ID"] = task["id"]
    env["AUTONOMOUS_RUN_NONCE"] = run_nonce
    env["AUTONOMOUS_ALLOWED_PATHS"] = json.dumps(task["allowed_paths"], ensure_ascii=False)
    # Remove any prior summary so a failed/stalled runtime can never inherit an old PASS.
    try:
        summary.unlink()
    except FileNotFoundError:
        pass

    status = "FAIL"
    payload: dict[str, object] = {}
    exit_code = 1
    failure_reason = ""
    global ACTIVE_PROCESS
    process = subprocess.Popen(
        [sys.executable, "scripts/run_guarded_runtime.py"],
        cwd=ROOT,
        env=env,
        text=True,
        start_new_session=True,
    )
    ACTIVE_PROCESS = process
    deadline = datetime.now(timezone.utc).timestamp() + 1800
    try:
        while process.poll() is None:
            if stopped(stop_file):
                failure_reason = "stop_requested_during_task"
                _kill_process_group(process)
                break
            if datetime.now(timezone.utc).timestamp() >= deadline:
                failure_reason = "task_timeout"
                _kill_process_group(process)
                break
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            _kill_process_group(process)
    exit_code = process.returncode if process.returncode is not None else 1
    ACTIVE_PROCESS = None

    if summary.exists():
        try:
            candidate = json.loads(summary.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                payload = candidate
            else:
                failure_reason = failure_reason or "summary_not_object"
        except (OSError, ValueError):
            failure_reason = failure_reason or "summary_invalid_json"

    required = {"timestamp", "status", "exit_code", "base_sha", "produced_sha", "task_id", "run_nonce"}
    if not required.issubset(payload):
        failure_reason = failure_reason or "summary_missing_required_key"
    elif not _valid_sha(base_sha) or not _valid_sha(payload.get("produced_sha")):
        failure_reason = failure_reason or "summary_sha_invalid"
    elif payload.get("exit_code") != exit_code:
        failure_reason = failure_reason or "summary_exit_code_mismatch"
    else:
        try:
            summary_time = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00"))
            now_time = datetime.now(timezone.utc)
            if summary_time < start_time:
                failure_reason = failure_reason or "summary_stale"
            elif summary_time > now_time:
                failure_reason = failure_reason or "summary_timestamp_future"
        except (TypeError, ValueError):
            failure_reason = failure_reason or "summary_timestamp_invalid"
        if payload.get("task_id") != task["id"] or payload.get("run_nonce") != run_nonce:
            failure_reason = failure_reason or "summary_identity_mismatch"
        if payload.get("base_sha") != base_sha:
            failure_reason = failure_reason or "summary_base_sha_mismatch"

    if stopped(stop_file):
        failure_reason = failure_reason or "stop_requested_after_task"

    produced_sha = _git_head()
    if payload:
        status = str(payload.get("status", "FAIL"))

    # A successful exit code is not sufficient evidence: status and produced SHA
    # must agree with the observed repository state.
    if payload and exit_code == 0 and not failure_reason:
        if payload.get("status") not in VALID_RUNTIME_STATUSES:
            failure_reason = "summary_status_invalid"
        elif payload.get("produced_sha") != produced_sha:
            failure_reason = "summary_produced_sha_mismatch"
        elif payload.get("status") == "NO_CHANGE" and produced_sha != base_sha:
            failure_reason = "summary_no_change_but_head_moved"

    # A zero exit code with an unchanged HEAD is the only valid NO_CHANGE.
    # A failed runtime must never be reclassified as NO_CHANGE merely because
    # its rollback restored the base SHA; otherwise the report hides the
    # actual guarded-runtime failure.
    if exit_code == 0 and produced_sha == base_sha and _valid_sha(base_sha):
        failure_reason = failure_reason or "no_change"
        status = "NO_CHANGE"
    elif exit_code != 0 and not failure_reason:
        failure_reason = "task_runtime_failed"

    if exit_code == 0 and not failure_reason:
        verified, reason = _verify_produced_head(base_sha, produced_sha, task["allowed_paths"])
        if not verified:
            failure_reason = reason

    if exit_code != 0 or failure_reason:
        if failure_reason == "no_change" and exit_code == 0:
            status = "NO_CHANGE"
        elif failure_reason == "task_timeout":
            status = "TIMEOUT"
        elif "stop_requested" in failure_reason:
            status = "STOPPED"
        else:
            status = "FAIL"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_index": run_index,
        "task_id": task["id"],
        "run_nonce": run_nonce,
        "status": status,
        "exit_code": exit_code,
        "base_sha": base_sha,
        "produced_sha": produced_sha,
        "failure_reason": failure_reason,
    }


def _handle_signal(signum: int, _frame) -> None:
    global ACTIVE_RESUME_CONTEXT
    process = ACTIVE_PROCESS
    if process is not None:
        _kill_process_group(process)
    if ACTIVE_RESUME_CONTEXT is not None:
        store, task_id = ACTIVE_RESUME_CONTEXT
        try:
            store.hold_interrupted_resume(task_id, reason="signal_interrupted_resume")
        except Exception:
            pass
        ACTIVE_RESUME_CONTEXT = None
    raise SystemExit(128 + signum)


def should_attempt_bounded_repair(
    result: dict[str, object],
    recovery_decision: dict[str, object],
    *,
    stop_requested: bool,
) -> bool:
    """Allow one automatic repair pass only for a clean, unchanged timeout."""
    return (
        not stop_requested
        and result.get("status") == "TIMEOUT"
        and result.get("failure_reason") == "task_timeout"
        and result.get("base_sha") == result.get("produced_sha")
        and bool(_valid_sha(result.get("base_sha")))
        and recovery_decision.get("action") == "REPAIR_ONCE"
    )


def build_bounded_repair_task(
    task: dict[str, object], failure_reason: str
) -> dict[str, object]:
    """Add a sanitized repair instruction without changing the task's path allowlist."""
    if failure_reason != "task_timeout":
        raise ValueError("automatic repair reason is not allowlisted")
    instruction = str(task.get("instruction", "")).strip()
    allowed_paths = task.get("allowed_paths")
    if not instruction or not isinstance(allowed_paths, list) or not allowed_paths:
        raise ValueError("automatic repair task is invalid")
    return {
        **task,
        "instruction": (
            instruction
            + "\n\nRecovery AI automatic repair attempt (1 of 1): "
            + "the prior attempt timed out before changing the repository. "
            + "Inspect the task and its allowed files, make one focused correction "
            + "to prevent the timeout, and run the required checks. Do not expand "
            + "the allowed paths. Do not merge, deploy, access secrets, or retry again. "
            + "If the cause cannot be established safely, stop without changes."
        ),
    }


def resume_held_task_for_run(
    task_id: str | None,
    *,
    cause_fixed: bool,
    queued_tasks: list[dict[str, object]],
    completed: set[str],
    recovery_store,
    actor: str | None = None,
    run_id: str | None = None,
) -> str | None:
    """Resume one explicitly confirmed held queue task; never resume arbitrary IDs."""
    if not task_id:
        if cause_fixed:
            raise ValueError("cause_fixed confirmation requires a task ID")
        return None
    if cause_fixed is not True:
        raise ValueError("explicit cause_fixed confirmation is required")
    queued_ids = {str(task.get("id", "")) for task in queued_tasks if isinstance(task, dict)}
    if task_id not in queued_ids:
        raise ValueError("resume task ID is not present in the current queue")
    if task_id in completed:
        raise ValueError("completed tasks cannot be resumed")
    recovery_store.resume_held_task(task_id, cause_fixed=True, actor=actor, run_id=run_id)
    return task_id


def main() -> int:
    global ACTIVE_RESUME_CONTEXT
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("--stop-file", type=Path, default=DEFAULT_STOP_FILE)
    parser.add_argument("--results", type=Path, default=Path("/tmp/minimal-autonomous-loop.jsonl"))
    parser.add_argument("--state", type=Path, default=Path("/tmp/autonomous-loop-state.json"))
    parser.add_argument("--incident-category", choices=sorted(INCIDENT_CATEGORIES))
    parser.add_argument("--incident-detail", choices=sorted(INCIDENT_DETAILS))
    parser.add_argument("--incident-job-id")
    parser.add_argument("--resume-task-id")
    parser.add_argument("--resume-actor")
    parser.add_argument("--resume-run-id")
    parser.add_argument("--confirm-cause-fixed", action="store_true")
    args = parser.parse_args()

    if args.max_tasks < 1 or args.max_tasks > 4:
        raise SystemExit("--max-tasks must be between 1 and 4")

    queue_data = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue_limit = int(queue_data.get("max_tasks_per_run", 3))
    if args.max_tasks > queue_limit:
        raise SystemExit(f"--max-tasks exceeds queue max_tasks_per_run={queue_limit}")
    completed = load_completed(args.state)
    queued_tasks: list[dict[str, object]] = []
    if args.incident_category is not None:
        if args.max_tasks != 2 or args.incident_detail is None:
            raise SystemExit("Obsidian incident mode requires exactly two tasks and an allowlisted detail")
        tasks = incident_tasks(args.incident_category, args.incident_detail, args.incident_job_id)
    else:
        if args.incident_detail is not None or args.incident_job_id is not None:
            raise SystemExit("incident detail/job ID require incident category")
        queued_tasks = load_tasks()
        tasks = [task for task in queued_tasks if task["id"] not in completed]

    # Recovery state is read before selection so tasks already held after repeated
    # failures cannot be run again automatically on the next scheduled invocation.
    from scripts.recovery_ai import RecoveryStore
    recovery_store = RecoveryStore(args.state.parent / "recovery-ai-state.json")
    resumed_task_id = None
    if args.resume_task_id is not None or args.confirm_cause_fixed:
        if args.incident_category is not None:
            raise SystemExit("held-task resume is unavailable in incident mode")
        try:
            resumed_task_id = resume_held_task_for_run(
                args.resume_task_id,
                cause_fixed=args.confirm_cause_fixed,
                queued_tasks=queued_tasks,
                completed=completed,
                recovery_store=recovery_store,
                actor=args.resume_actor,
                run_id=args.resume_run_id,
            )
        except (ValueError, RuntimeError) as exc:
            raise SystemExit(f"held-task resume rejected: {exc}") from exc
    pending_tasks = list(tasks)
    # An explicit resume run must execute only the selected task. Never unhold
    # one task and then accidentally run an earlier queue item instead.
    if resumed_task_id is not None:
        pending_tasks = [task for task in pending_tasks if str(task["id"]) == resumed_task_id]
        if not pending_tasks:
            raise SystemExit("held-task resume rejected: target is not pending in this run")
    tasks = [
        task for task in pending_tasks
        if recovery_store.task_status(str(task["id"])).get("held") is not True
    ]
    if pending_tasks and not tasks:
        args.results.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "BLOCKED",
            "task_id": "",
            "task_count": 0,
            "queue_total": len(queued_tasks) if queued_tasks else len(pending_tasks),
            "queue_completed": sum(1 for task in queued_tasks if task["id"] in completed),
            "exit_code": 79,
            "failure_reason": "all_pending_tasks_held",
        }
        with args.results.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print("MINIMAL_LOOP=BLOCKED reason=all_pending_tasks_held", flush=True)
        return 79
    tasks = tasks[: args.max_tasks]

    if not tasks:
        queued_ids = [str(task["id"]) for task in queued_tasks]
        args.results.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "NOT_RUN",
            "task_id": "",
            "task_count": 0,
            "queue_total": len(queued_ids),
            "queue_completed": sum(1 for task_id in queued_ids if task_id in completed),
            "exit_code": EXIT_NOT_RUN,
            "failure_reason": NOT_RUN_REASON_QUEUE_EMPTY,
        }
        with args.results.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"MINIMAL_LOOP=NOT_RUN reason={NOT_RUN_REASON_QUEUE_EMPTY} (no task was executed)", flush=True)
        return EXIT_NOT_RUN

    args.results.parent.mkdir(parents=True, exist_ok=True)
    budget_seconds = int(os.environ.get("AUTONOMOUS_LOOP_BUDGET_SECONDS", "0") or 0)
    loop_started = time.monotonic()
    for index, task in enumerate(tasks, 1):
        if budget_seconds > 0 and budget_seconds - (time.monotonic() - loop_started) < 1800:
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "BUDGET_EXHAUSTED",
                "task_id": str(task["id"]),
                "run_index": index,
                "exit_code": 80,
                "failure_reason": "loop_budget_insufficient_for_task",
            }
            with args.results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            print("MINIMAL_LOOP=HALT reason=loop_budget_insufficient_for_task", flush=True)
            return 80
        if stopped(args.stop_file):
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_index": index,
                "task_id": task["id"],
                "status": "STOPPED",
                "exit_code": 1,
                "failure_reason": "stop_requested_before_task",
            }
            with args.results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"MINIMAL_LOOP=STOPPED before task={task['id']}")
            return 1

        print(f"MINIMAL_LOOP=RUN task={task['id']} index={index}/{len(tasks)}", flush=True)
        result = run_task(task, index, args.stop_file)
        recovery_error = False
        try:
            from scripts.recovery_ai_loop_adapter import record_loop_outcome
            result["recovery_ai"] = record_loop_outcome(
                args.state.parent / "recovery-ai-state.json", result
            )
            recovery_decision = result["recovery_ai"].get("decision", {})
            if (
                should_attempt_bounded_repair(
                    result,
                    recovery_decision if isinstance(recovery_decision, dict) else {},
                    stop_requested=stopped(args.stop_file),
                )
                and (budget_seconds <= 0 or budget_seconds - (time.monotonic() - loop_started) >= 1800)
            ):
                prior_failure_reason = str(result.get("failure_reason", ""))
                repair_task = build_bounded_repair_task(task, prior_failure_reason)
                repaired = run_task(repair_task, index, args.stop_file)
                repaired["automatic_repair"] = {
                    "attempted": True,
                    "attempt": 1,
                    "max_attempts": 1,
                    "trigger": "task_timeout",
                    "prior_attempt_status": "TIMEOUT",
                    "prior_failure_reason": prior_failure_reason,
                    "prior_attempt_sha_unchanged": True,
                }
                repaired["recovery_ai"] = record_loop_outcome(
                    args.state.parent / "recovery-ai-state.json", repaired
                )
                result = repaired
        except Exception:
            # Do not report PASS or proceed to another task unless the recovery
            # decision can be durably recorded and read back.
            recovery_error = True
            result["status"] = "FAIL"
            result["exit_code"] = 1
            result["failure_reason"] = "recovery_ai_state_persist_failed"
            result["recovery_ai"] = {
                "recorded": False,
                "reason": "state_persistence_failed",
            }

        if resumed_task_id is not None:
            audit = recovery_store.task_status(resumed_task_id)
            result["resume_audit"] = {
                "task_id": resumed_task_id,
                "resume_count": audit.get("resume_count", 0),
                "operator": audit.get("resume_actor", "unknown"),
                "workflow_run_id": audit.get("resume_run_id", "unknown"),
                "review_status": "audit_only_not_an_approval_gate",
            }

        with args.results.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")

        if recovery_error:
            print(
                f"MINIMAL_LOOP=HALT task={task['id']} reason=recovery_ai_state_persist_failed",
                flush=True,
            )
            return 1

        if result["exit_code"] != 0 or result["status"] not in {"PASS", "NO_CHANGE"}:
            print(f"MINIMAL_LOOP=HALT task={task['id']} status={result['status']}", flush=True)
            return 1

        print(f"MINIMAL_LOOP={result['status']} task={task['id']}", flush=True)

    print("MINIMAL_LOOP=COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
