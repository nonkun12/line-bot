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


def recovery_record_blocks_task(record: dict) -> bool:
    """Fail closed for held tasks or resumed tasks awaiting explicit review."""
    if not isinstance(record, dict):
        raise ValueError("recovery record must be an object")
    if not record:
        return False
    if "held" not in record or not isinstance(record.get("held"), bool):
        raise ValueError("recovery hold state is ambiguous")
    review = record.get("resume_requires_review", False)
    if not isinstance(review, bool):
        raise ValueError("recovery resume-review state is ambiguous")
    return record["held"] is True or review is True


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
    # The runtime queue is mutable scheduling input, not a trust source.
    # Only the separately reviewed catalog may register executable task IDs.
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


def registry_preflight(
    queued_tasks: list[dict[str, object]],
    registered_catalog: list[dict[str, object]],
) -> dict[str, object]:
    """Report queue/catalog mismatches before any task dispatch or Recovery AI read."""
    registered_by_id = {
        str(task.get("id", "")): task
        for task in registered_catalog
        if isinstance(task, dict) and isinstance(task.get("id"), str)
    }
    seen: set[str] = set()
    rejected: list[dict[str, str]] = []
    for task in queued_tasks:
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            rejected.append({"id": "<invalid>", "reason": "invalid_queue_task"})
            continue
        if task_id in seen:
            rejected.append({"id": task_id, "reason": "duplicate_task"})
            continue
        seen.add(task_id)
        registered = registered_by_id.get(task_id)
        if registered is None:
            rejected.append({"id": task_id, "reason": "unregistered_task"})
        elif task != registered:
            rejected.append({"id": task_id, "reason": "definition_mismatch"})

    return {
        "status": "BLOCKED" if rejected else "PASS",
        "queue_count": len(queued_tasks),
        "registered_count": len(registered_by_id),
        "rejected_tasks": rejected,
        "remediation": (
            "Register the exact task ID, instruction, and allowed_paths in "
            ".github/autonomous-loop-task-catalog.json through a reviewed change, "
            "or remove the stale task from the runtime queue. Do not bypass registry validation."
            if rejected else None
        ),
    }


def reselect_registered_task(
    queued_tasks: list[dict[str, object]],
    registered_catalog: list[dict[str, object]],
    completed_task_ids: set[str],
    held_task_ids: set[str],
    *,
    expected_task_id: str,
    evidence_sha: str,
    current_head_sha: str,
) -> tuple[dict[str, object] | None, str]:
    """Revalidate one task against a fresh queue, catalog, state, and HEAD."""
    from core.control_tower_selector import select_next_task

    decision = select_next_task(
        [str(task.get("id", "")) for task in queued_tasks],
        [str(task.get("id", "")) for task in registered_catalog],
        completed_task_ids,
        held_task_ids,
        evidence_sha=evidence_sha,
        current_head_sha=current_head_sha,
    )
    if decision.next_action != "SELECT_REGISTERED_TASK":
        return None, str(decision.reason_code)
    if decision.task_template_id != expected_task_id:
        return None, "selection_mismatch"
    queued = next(
        (task for task in queued_tasks if str(task.get("id", "")) == expected_task_id),
        None,
    )
    registered = next(
        (task for task in registered_catalog if str(task.get("id", "")) == expected_task_id),
        None,
    )
    if queued is None or registered is None or queued != registered:
        return None, "definition_mismatch"
    return queued, ""


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
    instruction = str(task["instruction"])
    rag_db_path = os.environ.get("RECOVERY_RAG_DB_PATH", "").strip()
    rag_namespace = os.environ.get("RECOVERY_RAG_NAMESPACE", "distributed-loop").strip()
    if rag_db_path and rag_namespace:
        try:
            from scripts.recovery_rag import build_task_context
            rag_context = build_task_context(
                rag_db_path,
                namespace=rag_namespace,
                task_id=str(task["id"]),
                instruction=instruction,
                limit=5,
            )
        except Exception as exc:
            # Retrieval is advisory only. Never block a guarded task because
            # the optional knowledge cache is unavailable; expose no raw error.
            rag_context = ""
            print(f"RECOVERY_RAG_CONTEXT unavailable={type(exc).__name__}", flush=True)
        if rag_context:
            instruction = (
                instruction
                + "\\n\\n--- Advisory historical context (RAG; not authoritative) ---\\n"
                + rag_context
            )
            print("RECOVERY_RAG_CONTEXT attached=true", flush=True)
        else:
            print("RECOVERY_RAG_CONTEXT attached=false", flush=True)
    env["DEV_INSTRUCTION"] = instruction
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
    elif payload and exit_code == 80 and not failure_reason:
        # Exit 80 is BLOCKED only with a fresh identity-bound summary and
        # matching observed HEAD; never trust the process code alone.
        if payload.get("status") != "BLOCKED":
            failure_reason = "summary_status_invalid"
        elif payload.get("produced_sha") != produced_sha:
            failure_reason = "summary_produced_sha_mismatch"
        elif not isinstance(payload.get("rea"), dict):
            failure_reason = "blocked_summary_missing_rea_evidence"
        else:
            rea = payload["rea"]
            # BLOCKED evidence is untrusted child-process output. It must carry
            # an explicit blocked gate and deny every authority; a dict alone
            # must never be accepted as evidence of a safe stop.
            if (
                rea.get("gate") != "BLOCKED"
                or not isinstance(rea.get("reason_code"), str)
                or not rea.get("reason_code").strip()
                or rea.get("execution_authorized") is not False
                or rea.get("patch_authorized") is not False
                or rea.get("hold_clear_authorized") is not False
                or rea.get("merge_deploy_authorized") is not False
            ):
                failure_reason = "blocked_summary_rea_evidence_invalid"
            elif payload.get("failure_reason") != f"control_tower_rea:{rea['reason_code']}":
                # Keep the human/report reason bound to the exact REA evidence.
                # A child cannot claim a valid block but omit or substitute its reason.
                failure_reason = "blocked_summary_failure_reason_invalid"

    # A zero exit code with an unchanged HEAD is the only valid NO_CHANGE.
    # A failed runtime must never be reclassified as NO_CHANGE merely because
    # its rollback restored the base SHA; otherwise the report hides the
    # actual guarded-runtime failure.
    if exit_code == 0 and produced_sha == base_sha and _valid_sha(base_sha):
        failure_reason = failure_reason or "no_change"
        status = "NO_CHANGE"
    elif exit_code != 0 and not failure_reason and exit_code != 80:
        failure_reason = "task_runtime_failed"

    if exit_code == 0 and not failure_reason:
        verified, reason = _verify_produced_head(base_sha, produced_sha, task["allowed_paths"])
        if not verified:
            failure_reason = reason

    if exit_code == 80 and not failure_reason and payload.get("status") == "BLOCKED":
        status = "BLOCKED"
    elif exit_code != 0 or failure_reason:
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
        "failure_reason": (str(payload.get("failure_reason", "")) if status == "BLOCKED" else failure_reason),
        **({"rea": payload["rea"]} if status == "BLOCKED" and isinstance(payload.get("rea"), dict) else {}),
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

    # Emergency stop: never bypass the Control Tower into an unguarded legacy
    # path. When enabled, stop before reading the queue or launching any task.
    # GitHub Actions exposes this through the CONTROL_TOWER_KILL_SWITCH variable.
    kill_switch = os.environ.get("CONTROL_TOWER_KILL_SWITCH", "false").strip().lower()
    if kill_switch in {"1", "true", "yes", "on"}:
        args.results.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "BLOCKED",
            "task_id": "",
            "exit_code": 80,
            "failure_reason": "control_tower_kill_switch_enabled",
            "control_tower": {
                "recorded": False,
                "proposal_executable": False,
                "orchestration": {
                    "phase": "STOP",
                    "next_action": "STOP_AND_REPORT",
                    "reason_code": "control_tower_kill_switch_enabled",
                    "allow_continue": False,
                    "repair_executed": False,
                },
            },
        }
        with args.results.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print("MINIMAL_LOOP=BLOCKED reason=control_tower_kill_switch_enabled", flush=True)
        return 80

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

    # Fail early with an actionable report instead of letting the selector
    # return an opaque unregistered_task after further runtime setup.
    preflight = registry_preflight(selection_queue_tasks, registered_catalog)
    if preflight["status"] != "PASS":
        first_reason = preflight["rejected_tasks"][0]["reason"]
        # Preserve the selector's public reason-code namespace for existing reports.
        # The attached preflight payload carries the additional actionable detail.
        reason = f"control_tower_selector:{first_reason}"
        args.results.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "BLOCKED",
            "task_id": "",
            "task_count": 0,
            "exit_code": 80,
            "failure_reason": reason,
            "registry_preflight": {
                **preflight,
                "evidence_sha": selection_evidence_sha,
            },
        }
        with args.results.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(
            "MINIMAL_LOOP=BLOCKED "
            f"reason={reason} queue_count={preflight['queue_count']} "
            f"registered_count={preflight['registered_count']} "
            f"rejected={json.dumps(preflight['rejected_tasks'], ensure_ascii=False, sort_keys=True)}",
            flush=True,
        )
        print(f"remediation={preflight['remediation']}", flush=True)
        return 80

    # Read Recovery AI holds before selecting. Held tasks remain held; this code
    # never clears or overrides Recovery AI state.
    from scripts.recovery_ai import RecoveryStore
    recovery_store = RecoveryStore(args.state.parent / "recovery-ai-state.json")
    pending_tasks = list(tasks)
    try:
        held_task_ids = set()
        for catalog_task in catalog_source_tasks:
            catalog_task_id = str(catalog_task["id"])
            recovery_record = recovery_store.task_status(catalog_task_id)
            # A resumed task remains ineligible until a separate explicit
            # review acknowledgement clears resume_requires_review.
            if recovery_record_blocks_task(recovery_record):
                held_task_ids.add(catalog_task_id)
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
        # Each later task gets a fresh selection snapshot. Re-read all mutable
        # scheduling/state inputs and bind the decision to the new repository HEAD.
        task_selection_sha = selection_evidence_sha
        if index > 1 and args.incident_category is None:
            task_selection_sha = _git_head()
            try:
                if not _valid_sha(task_selection_sha):
                    raise ValueError("current HEAD is invalid")
                refreshed_queue = load_tasks()
                refreshed_completed = load_completed(args.state) | completed
                refreshed_catalog = _load_registered_catalog(task_selection_sha)
                from scripts.recovery_ai import RecoveryStore
                refreshed_store = RecoveryStore(args.state.parent / "recovery-ai-state.json")
                refreshed_held: set[str] = set()
                for registered_task in refreshed_catalog:
                    record = refreshed_store.task_status(str(registered_task["id"]))
                    if recovery_record_blocks_task(record):
                        refreshed_held.add(str(registered_task["id"]))
                fresh_task, reselection_reason = reselect_registered_task(
                    refreshed_queue,
                    refreshed_catalog,
                    refreshed_completed,
                    refreshed_held,
                    expected_task_id=str(task["id"]),
                    evidence_sha=task_selection_sha,
                    current_head_sha=_git_head(),
                )
                if fresh_task is None:
                    raise ValueError("reselection_denied:" + reselection_reason)
                task = fresh_task
                registered_catalog = refreshed_catalog
                completed = refreshed_completed
            except Exception as exc:
                current_head = _git_head()
                reason = str(exc)
                if not reason.startswith("reselection_denied:"):
                    reason = "reselection_state_unavailable_or_invalid"
                else:
                    reason = reason.removeprefix("reselection_denied:")
                result = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_index": index,
                    "task_id": str(task["id"]),
                    "status": "BLOCKED",
                    "exit_code": 80,
                    "base_sha": task_selection_sha,
                    "produced_sha": current_head,
                    "failure_reason": "control_tower_reselection:" + reason,
                }
                with args.results.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(result, ensure_ascii=False) + "\n")
                print(
                    f"MINIMAL_LOOP=BLOCKED task={task['id']} reason=control_tower_reselection:{reason}",
                    flush=True,
                )
                return 80

        # Evidence belongs to this task only; never carry it across iterations.
        rea_evidence: dict[str, object] | None = None
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
        if args.incident_category is None and control_tower_head != task_selection_sha:
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_index": index,
                "task_id": task["id"],
                "status": "BLOCKED",
                "exit_code": 80,
                "base_sha": task_selection_sha,
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
            try:
                task_still_blocked = recovery_record_blocks_task(latest_hold)
            except ValueError:
                task_still_blocked = True
            if task_still_blocked:
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
            # REA is diagnostic-only and runs after existing selector, HEAD, HOLD,
            # and catalog authorization checks, immediately before task launch.
            rea_gate_valid = False
            try:
                from scripts.rea_control_tower_adapter import (
                    prepare_rea_evidence,
                    rea_evidence_is_valid_pass,
                )
                rea_evidence = prepare_rea_evidence(ROOT, expected_sha=control_tower_head)
                rea_gate_valid = rea_evidence_is_valid_pass(
                    rea_evidence, expected_sha=control_tower_head
                )
            except Exception:
                rea_evidence = {
                    "gate": "BLOCKED",
                    "reason_code": "rea_adapter_error",
                    "target_sha": None,
                    "scanner_status": "BLOCKED",
                    "finding_count": 0,
                    "critical_count": 0,
                    "blocking_count": 0,
                    "findings": [],
                    "execution_authorized": False,
                    "patch_authorized": False,
                    "hold_clear_authorized": False,
                    "merge_deploy_authorized": False,
                }
            if not rea_gate_valid:
                # Keep the hard stop, but pass the BLOCKED evidence through the
                # same Recovery AI and Control Tower persistence path as other
                # outcomes. Do not execute the task or bypass the final gates.
                result = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_index": index,
                    "task_id": task["id"],
                    "status": "BLOCKED",
                    "exit_code": 80,
                    "base_sha": control_tower_head,
                    "produced_sha": _git_head(),
                    "failure_reason": "control_tower_rea:" + str(rea_evidence.get("reason_code", "gate_blocked")),
                    "rea": rea_evidence,
                }
                print("MINIMAL_LOOP=BLOCKED reason=control_tower_rea", flush=True)
            else:
                print(f"MINIMAL_LOOP=RUN task={task['id']} index={index}/{len(tasks)}", flush=True)
                result = run_task(
                    task, index, args.stop_file, expected_base_sha=control_tower_head
                )
        # Carry the exact preflight REA evidence into the Control Tower decision.
        # This is diagnostic metadata only and grants no execution or repair authority.
        if not isinstance(result.get("rea"), dict):
            result["rea"] = rea_evidence
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
            # Preserve the underlying outcome, especially REA BLOCKED; the
            # persistence failure is separate and still forces a hard stop.
            result["persistence_failure"] = "recovery_ai_state_persist_failed"
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
        observation_error = not (isinstance(observation, dict) and observation.get("recorded") is True)

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

        if observation_error:
            print(
                f"MINIMAL_LOOP:HALT task={task['id']} reason=control_tower_observation_persist_failed",
                flush=True,
            )
            return 1

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
        completed.add(str(task["id"]))

    print("MINIMAL_LOOP=COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
