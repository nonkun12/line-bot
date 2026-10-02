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
QUEUE = ROOT / ".github" / "autonomous-loop-tasks.json"
DEFAULT_STOP_FILE = Path("/tmp/line-bot-autonomous-loop.stop")
ACTIVE_PROCESS: subprocess.Popen[str] | None = None


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


def run_task(task: dict[str, object], run_index: int, stop_file: Path, summary_dir: Path = Path("/tmp")) -> dict[str, object]:
    summary = summary_dir / f"minimal-autonomous-{task['id']}.json"
    run_nonce = uuid.uuid4().hex
    start_time = datetime.now(timezone.utc)
    base_sha = _git_head()
    env = os.environ.copy()
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
    if produced_sha == base_sha and _valid_sha(base_sha):
        failure_reason = failure_reason or "no_change"
        status = "NO_CHANGE"
    elif payload:
        status = str(payload.get("status", "FAIL"))
    if not failure_reason:
        verified, reason = _verify_produced_head(base_sha, produced_sha, task["allowed_paths"])
        if not verified:
            failure_reason = reason

    if exit_code != 0 or failure_reason:
        if failure_reason == "no_change":
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
        "tests_result": str(payload.get("tests_result", "NOT_REPORTED")),
        "verification_result": str(payload.get("verification_result", "NOT_REPORTED")),
        "safety_gate_result": str(payload.get("safety_gate_result", "BLOCKED")),
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
    args = parser.parse_args()

    if args.max_tasks < 1 or args.max_tasks > 3:
        raise SystemExit("--max-tasks must be between 1 and 3")

    queue_data = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue_limit = int(queue_data.get("max_tasks_per_run", 3))
    if args.max_tasks > queue_limit:
        raise SystemExit(f"--max-tasks exceeds queue max_tasks_per_run={queue_limit}")
    completed = load_completed(args.state)
    tasks = [task for task in load_tasks() if task["id"] not in completed][: args.max_tasks]
    if not tasks:
        print("MINIMAL_LOOP=COMPLETE queue exhausted")
        return 0

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
                "tests_result": "NOT_REPORTED",
                "verification_result": "NOT_REPORTED",
                "safety_gate_result": "BLOCKED",
            }
            with args.results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"MINIMAL_LOOP=STOPPED before task={task['id']}")
            return 1

        print(f"MINIMAL_LOOP=RUN task={task['id']} index={index}/{len(tasks)}", flush=True)
        result = run_task(task, index, args.stop_file)
        with args.results.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")

        if result["exit_code"] != 0 or result["status"] not in {"PASS", "NO_CHANGE"}:
            print(f"MINIMAL_LOOP=HALT task={task['id']} status={result['status']}", flush=True)
            return 1

        print(f"MINIMAL_LOOP={result['status']} task={task['id']}", flush=True)

    print("MINIMAL_LOOP=COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())