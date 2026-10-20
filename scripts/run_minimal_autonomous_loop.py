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
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Running this file as `python scripts/run_minimal_autonomous_loop.py` puts
# scripts/ (not the repository root) at sys.path[0]. Add ROOT explicitly so
# fail-closed Recovery AI imports work in GitHub Actions and local invocations.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
QUEUE = Path(os.environ.get("AUTONOMOUS_LOOP_TASK_QUEUE", str(ROOT / ".github" / "autonomous-loop-tasks.json"))).resolve()
DEFAULT_STOP_FILE = Path("/tmp/line-bot-autonomous-loop.stop")
ACTIVE_PROCESS: subprocess.Popen[str] | None = None

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
                # Recovery persistence is an additional gate only when it was
                # actually attempted/reported. Missing is not the same as failure.
                *([("recovery_ai_persistence", recovery_outcome)] if recovery_outcome is not None else []),
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
                # Recovery persistence is an additional gate only when it was
                # actually attempted/reported. Missing is not the same as failure.
                *([("recovery_ai_persistence", recovery_outcome)] if recovery_outcome is not None else []),
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


def _load_registered_catalog(evidence_sha: str) -> list[dict[str, object]]:
    """Load task definitions from version-controlled catalogs at the selection commit.

    The runtime queue is intentionally not a source of trust: it only selects
    among definitions reviewed into one of the repository catalogs.
    """
    if not _valid_sha(evidence_sha):
        raise ValueError("catalog evidence SHA is invalid")
    catalog_paths = (
        ".github/autonomous-loop-task-catalog.json",
    )
    definitions: dict[str, dict[str, object]] = {}
    for path in catalog_paths:
        code, raw = _git_checked("show", f"{evidence_sha}:{path}")
        if code != 0:
            raise ValueError("versioned task catalog unavailable")
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("versioned task catalog is invalid") from exc
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(tasks, list):
            raise ValueError("versioned task catalog has no task list")
        for entry in tasks:
            if not isinstance(entry, dict):
                raise ValueError("versioned task definition is invalid")
            task_id = entry.get("id")
            instruction = entry.get("instruction")
            allowed_paths = entry.get("allowed_paths")
            if (
                not isinstance(task_id, str)
                or not task_id.strip()
                or not isinstance(instruction, str)
                or not instruction.strip()
                or not isinstance(allowed_paths, list)
                or not allowed_paths
                or not all(isinstance(item, str) and item.strip() for item in allowed_paths)
            ):
                raise ValueError("versioned task definition is invalid")
            normalized = {
                "id": task_id,
                "instruction": instruction,
                "allowed_paths": [item.strip() for item in allowed_paths],
            }
            previous = definitions.get(task_id)
            if previous is not None and previous != normalized:
                raise ValueError("conflicting versioned task definitions")
            definitions[task_id] = normalized
    return list(definitions.values())


def _verify_produced_head(base_sha: str, produced_sha: str, allowed_paths: list[str]) -> tuple[bool, str]:
    if not _valid_sha(base_sha) or not _valid_sha(produced_sha):
        return False, "sha_invalid"
    if _git_head() != produced_sha:
        return False, "produced_sha_head_mismatch"
    code, _ = _git_checked("merge-base", "--is-ancestor", base_sha, produced_sha)
    if code != 0:
        return False, "produced_not_descendant_of_base"
    code, diff = _git_checked("diff", "--no-renames", "--name-only", base_sha, produced_sha)
    if code != 0:
        return False, "diff_unavailable"
    # Never normalize an untrusted path: normalization can turn traversal into an
    # apparently safe path. Allowed paths must be literal repository-relative files.
    allowed = set()
    for raw_path in allowed_paths:
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or raw_path != raw_path.strip()
            or raw_path.startswith("/")
            or "\\" in raw_path
            or any(part in {"", ".", ".."} for part in raw_path.split("/"))
            or (len(raw_path) >= 2 and raw_path[1] == ":")
        ):
            return False, "allowed_paths_invalid"
        allowed.add(raw_path)
    if not allowed:
        return False, "allowed_paths_invalid"
    changed = {line for line in diff.splitlines() if line}
    if not changed.issubset(allowed):
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


def run_task(
    task: dict[str, object],
    run_index: int,
    stop_file: Path,
    summary_dir: Path = Path("/tmp"),
    *,
    expected_base_sha: str | None = None,
) -> dict[str, object]:
    summary = summary_dir / f"minimal-autonomous-{task['id']}.json"
    run_nonce = uuid.uuid4().hex
    start_time = datetime.now(timezone.utc)
    base_sha = _git_head()
    if expected_base_sha is not None and base_sha != expected_base_sha:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_index": run_index,
            "task_id": task["id"],
            "run_nonce": run_nonce,
            "status": "BLOCKED",
            "exit_code": 1,
            "base_sha": expected_base_sha,
            "produced_sha": base_sha,
            "failure_reason": "control_tower_head_changed",
        }
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
    process = ACTIVE_PROCESS
    if process is not None:
        _kill_process_group(process)
    raise SystemExit(128 + signum)


def main() -> int:
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
    args = parser.parse_args()

    if args.max_tasks < 1 or args.max_tasks > 4:
        raise SystemExit("--max-tasks must be between 1 and 4")

    # Bind selection to a repository snapshot taken before queue/state reads.
    # The selector independently re-reads HEAD after those reads and blocks if it moved.
    selection_evidence_sha = _git_head()
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
        catalog_source_tasks = list(tasks)
        selection_queue_tasks = list(tasks)
    else:
        if args.incident_detail is not None or args.incident_job_id is not None:
            raise SystemExit("incident detail/job ID require incident category")
        queued_tasks = load_tasks()
        catalog_source_tasks = queued_tasks
        selection_queue_tasks = queued_tasks
        tasks = [task for task in queued_tasks if task["id"] not in completed]

        # The selector currently authorizes only the first queued task against
        # this immutable HEAD snapshot. Until each subsequent task is reselected
        # and re-authorized against its own current HEAD, refuse multi-task normal
        # runs rather than executing queue entries under stale selection evidence.
        if args.max_tasks > 1:
            args.results.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "BLOCKED",
                "task_id": "",
                "task_count": 0,
                "exit_code": 80,
                "failure_reason": "control_tower_multi_task_reselection_unavailable",
            }
            with args.results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(
                "MINIMAL_LOOP=BLOCKED reason=control_tower_multi_task_reselection_unavailable",
                flush=True,
            )
            return 80

    # Normal queue entries are authorized only against Git-versioned catalogs
    # at the same immutable commit used as the selection evidence. Never derive
    # the trust catalog from the runtime queue itself.
    if args.incident_category is not None:
        registered_catalog = [
            {**task, "allowed_paths": list(task["allowed_paths"])}
            for task in catalog_source_tasks
        ]
    else:
        try:
            registered_catalog = _load_registered_catalog(selection_evidence_sha)
        except Exception:
            args.results.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "BLOCKED",
                "task_id": "",
                "task_count": 0,
                "exit_code": 80,
                "failure_reason": "control_tower_catalog:catalog_unavailable_or_invalid",
            }
            with args.results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            print("MINIMAL_LOOP=BLOCKED reason=control_tower_catalog:catalog_unavailable_or_invalid", flush=True)
            return 80

    # Read Recovery AI holds before selecting. Held tasks remain held; this code
    # never clears or overrides Recovery AI state.
    from scripts.recovery_ai import RecoveryStore
    recovery_store = RecoveryStore(args.state.parent / "recovery-ai-state.json")
    pending_tasks = list(tasks)
    try:
        held_task_ids = {
            str(task["id"])
            for task in catalog_source_tasks
            if recovery_store.task_status(str(task["id"])).get("held") is True
        }
    except Exception:
        # Malformed/unavailable Recovery AI state must produce auditable BLOCKED
        # evidence rather than crashing without a result row.
        args.results.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "BLOCKED",
            "task_id": "",
            "task_count": 0,
            "exit_code": 80,
            "failure_reason": "control_tower_recovery_state:unavailable_or_invalid",
        }
        with args.results.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(
            "MINIMAL_LOOP=BLOCKED reason=control_tower_recovery_state:unavailable_or_invalid",
            flush=True,
        )
        return 80
    tasks = [task for task in pending_tasks if str(task["id"]) not in held_task_ids]

    selection_decision = None
    if args.incident_category is None:
        try:
            from core.control_tower_selector import select_next_task
            selection_decision = select_next_task(
                [str(task["id"]) for task in selection_queue_tasks],
                [str(task["id"]) for task in registered_catalog],
                completed,
                held_task_ids,
                evidence_sha=selection_evidence_sha,
                current_head_sha=_git_head(),
            )
        except Exception:
            selection_decision = None

        if selection_decision is None or (
            selection_decision.next_action == "HOLD"
            and selection_decision.reason_code != "task_held"
        ):
            reason = (
                selection_decision.reason_code
                if selection_decision is not None
                else "selector_error"
            )
            args.results.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "BLOCKED",
                "task_id": "",
                "task_count": 0,
                "exit_code": 80,
                "failure_reason": f"control_tower_selector:{reason}",
            }
            with args.results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"MINIMAL_LOOP=BLOCKED reason=control_tower_selector:{reason}", flush=True)
            return 80

        if selection_decision.next_action == "SELECT_REGISTERED_TASK":
            if not tasks or str(tasks[0]["id"]) != selection_decision.task_template_id:
                args.results.parent.mkdir(parents=True, exist_ok=True)
                record = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "BLOCKED",
                    "task_id": "",
                    "task_count": 0,
                    "exit_code": 80,
                    "failure_reason": "control_tower_selector:selection_mismatch",
                }
                with args.results.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                print("MINIMAL_LOOP=BLOCKED reason=control_tower_selector:selection_mismatch", flush=True)
                return 80
        elif selection_decision.next_action not in {"NOT_RUN", "HOLD"}:
            args.results.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "BLOCKED",
                "task_id": "",
                "task_count": 0,
                "exit_code": 80,
                "failure_reason": "control_tower_selector:unexpected_action",
            }
            with args.results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            print("MINIMAL_LOOP=BLOCKED reason=control_tower_selector:unexpected_action", flush=True)
            return 80

        # A non-select decision is valid only when there is nothing executable.
        # This prevents a malformed/future selector result from being ignored.
        elif tasks:
            args.results.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "BLOCKED",
                "task_id": "",
                "task_count": 0,
                "exit_code": 80,
                "failure_reason": "control_tower_selector:action_task_mismatch",
            }
            with args.results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            print("MINIMAL_LOOP=BLOCKED reason=control_tower_selector:action_task_mismatch", flush=True)
            return 80
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
            "failure_reason": (
                selection_decision.reason_code
                if selection_decision is not None
                else NOT_RUN_REASON_QUEUE_EMPTY
            ),
        }
        with args.results.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        not_run_reason = (
            selection_decision.reason_code
            if selection_decision is not None
            else NOT_RUN_REASON_QUEUE_EMPTY
        )
        print(f"MINIMAL_LOOP=NOT_RUN reason={not_run_reason} (no task was executed)", flush=True)
        return EXIT_NOT_RUN

    args.results.parent.mkdir(parents=True, exist_ok=True)
    for index, task in enumerate(tasks, 1):
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

        # Control Tower preflight: exact registered definition + current HEAD.
        # The SHA is passed into run_task and rechecked before process creation
        # to close the validation/launch race. Failure blocks this run closed.
        control_tower_head = _git_head()
        if args.incident_category is None and control_tower_head != selection_evidence_sha:
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_index": index,
                "task_id": task["id"],
                "status": "BLOCKED",
                "exit_code": 80,
                "base_sha": selection_evidence_sha,
                "produced_sha": control_tower_head,
                "failure_reason": "control_tower_gate:selection_head_changed",
            }
            with args.results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"MINIMAL_LOOP=BLOCKED task={task['id']} reason=selection_head_changed", flush=True)
            return 80

        # Re-read HOLD immediately before launch; errors fail closed.
        try:
            from scripts.recovery_ai import RecoveryStore
            latest_hold = RecoveryStore(args.state.parent / "recovery-ai-state.json").task_status(str(task["id"]))
            # An empty record means this registered task has no recovery history yet.
            # A non-empty record with missing/invalid held state is ambiguous and blocks.
            malformed_hold = (
                not isinstance(latest_hold, dict)
                or (bool(latest_hold) and (
                    "held" not in latest_hold
                    or not isinstance(latest_hold.get("held"), bool)
                ))
            )
            if malformed_hold or latest_hold.get("held", False) is not False:
                result = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_index": index,
                    "task_id": task["id"],
                    "status": "BLOCKED",
                    "exit_code": 80,
                    "base_sha": control_tower_head,
                    "produced_sha": control_tower_head,
                    "failure_reason": "recovery_ai_hold_or_status_uncertain",
                }
                with args.results.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(result, ensure_ascii=False) + "\n")
                print(f"MINIMAL_LOOP=BLOCKED task={task['id']} reason=recovery_ai_hold_or_status_uncertain", flush=True)
                return 80
        except Exception:
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_index": index,
                "task_id": task["id"],
                "status": "BLOCKED",
                "exit_code": 80,
                "base_sha": control_tower_head,
                "produced_sha": control_tower_head,
                "failure_reason": "recovery_ai_hold_check_failed",
            }
            with args.results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"MINIMAL_LOOP=BLOCKED task={task['id']} reason=recovery_ai_hold_check_failed", flush=True)
            return 80

        try:
            from scripts.control_tower_loop_adapter import authorize_registered_task
            authorized, authorization_reason = authorize_registered_task(
                task, registered_catalog, control_tower_head
            )
        except Exception:
            authorized, authorization_reason = False, "control_tower_adapter_error"

        if not authorized:
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_index": index,
                "task_id": task["id"],
                "status": "BLOCKED",
                "exit_code": 1,
                "base_sha": control_tower_head,
                "produced_sha": _git_head(),
                "failure_reason": f"control_tower_gate:{authorization_reason}",
            }
            print(
                f"MINIMAL_LOOP=HALT task={task['id']} reason=control_tower_gate",
                flush=True,
            )
        else:
            print(f"MINIMAL_LOOP=RUN task={task['id']} index={index}/{len(tasks)}", flush=True)
            result = run_task(
                task, index, args.stop_file, expected_base_sha=control_tower_head
            )
        recovery_error = False
        try:
            from scripts.recovery_ai_loop_adapter import record_loop_outcome
            result["recovery_ai"] = record_loop_outcome(
                args.state.parent / "recovery-ai-state.json", result
            )
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

        # First persist a sanitized observation, then let the single
        # orchestrator combine it with the task and Recovery AI evidence.
        try:
            from scripts.control_tower_loop_observer import record_loop_observation
            observation = record_loop_observation(
                args.state.parent / "control-tower-observations.jsonl", result
            )
        except Exception:
            observation = {
                "recorded": False,
                "reason": "observation_or_persistence_failed",
                "proposal_executable": False,
            }
        result["control_tower"] = observation

        try:
            from scripts.control_tower_orchestrator import coordinate_outcome
            orchestration = coordinate_outcome(result)
        except Exception:
            orchestration = {
                "phase": "STOP",
                "next_action": "STOP_AND_REPORT",
                "reason_code": "orchestrator_error",
                "allow_continue": False,
                "repair_executed": False,
            }

        if result.get("status") in {"PASS", "NO_CHANGE"} and orchestration.get("allow_continue") is not True:
            # Keep durable Recovery AI aligned with the final fail-closed result.
            result["status"] = "FAIL"
            result["exit_code"] = 1
            result["failure_reason"] = "control_tower_orchestration_invalid_evidence"
            try:
                from scripts.recovery_ai_loop_adapter import record_loop_outcome
                result["recovery_ai"] = record_loop_outcome(
                    args.state.parent / "recovery-ai-state.json", result
                )
            except Exception:
                recovery_error = True
                result["recovery_ai"] = {"recorded": False, "reason": "state_persistence_failed"}
            try:
                observation = record_loop_observation(
                    args.state.parent / "control-tower-observations.jsonl", result
                )
            except Exception:
                observation = {
                    "recorded": False,
                    "reason": "observation_or_persistence_failed",
                    "proposal_executable": False,
                }
            result["control_tower"] = observation
            try:
                orchestration = coordinate_outcome(result)
            except Exception:
                orchestration = {
                    "phase": "STOP",
                    "next_action": "STOP_AND_REPORT",
                    "reason_code": "orchestrator_error",
                    "allow_continue": False,
                    "repair_executed": False,
                }

        result["control_tower"] = {**observation, "orchestration": orchestration}

        with args.results.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")

        if recovery_error:
            print(
                f"MINIMAL_LOOP:HALT task={task['id']} reason=recovery_ai_state_persist_failed",
                flush=True,
            )
            return 1

        if orchestration.get("allow_continue") is not True:
            print(
                f"MINIMAL_LOOP:HALT task={task['id']} reason={orchestration.get('reason_code', 'orchestration_blocked')}",
                flush=True,
            )
            return 1

        if result["exit_code"] != 0 or result["status"] not in {"PASS", "NO_CHANGE"}:
            print(f"MINIMAL_LOOP:HALT task={task['id']} status={result['status']}", flush=True)
            return 1

        print(f"MINIMAL_LOOP={result['status']} task={task['id']}", flush=True)

    print("MINIMAL_LOOP=COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
