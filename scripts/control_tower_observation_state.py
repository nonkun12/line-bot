"""Import/export sanitized Control Tower observations through durable loop state.

Observation history is advisory only. It cannot authorize tasks, alter outcomes,
or execute proposals. Malformed durable history fails closed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

MAX_RECORDS = 200
_SHA = re.compile(r"^[0-9a-f]{40}$")
_TASK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STATUSES = {"PASS", "NO_CHANGE", "FAIL", "BLOCKED", "NOT_RUN"}
_SIGNAL_KINDS = {"success", "repair", "failure"}


def sanitize(records: object) -> list[dict[str, object]]:
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError("control tower observations invalid")
    safe = []
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("control tower observation row invalid")
        task_id = row.get("task_id", "")
        status = row.get("status")
        exit_code = row.get("exit_code")
        base_sha = row.get("base_sha")
        produced_sha = row.get("produced_sha")
        timestamp = row.get("timestamp")
        if not isinstance(task_id, str) or (task_id and not _TASK.fullmatch(task_id)):
            raise ValueError("control tower task id invalid")
        if not isinstance(status, str) or status not in _STATUSES:
            raise ValueError("control tower status invalid")
        if exit_code is not None and type(exit_code) is not int:
            raise ValueError("control tower exit code invalid")
        for sha in (base_sha, produced_sha):
            if sha is not None and (not isinstance(sha, str) or not _SHA.fullmatch(sha)):
                raise ValueError("control tower SHA invalid")
        if not isinstance(timestamp, str) or len(timestamp) > 64:
            raise ValueError("control tower timestamp invalid")
        signals = row.get("signals", [])
        if not isinstance(signals, list) or len(signals) > 8:
            raise ValueError("control tower signals invalid")
        safe_signals = []
        for signal in signals:
            if not isinstance(signal, dict) or signal.get("kind") not in _SIGNAL_KINDS:
                raise ValueError("control tower signal invalid")
            signal_task = signal.get("task_id")
            if signal_task is not None and (not isinstance(signal_task, str) or not _TASK.fullmatch(signal_task)):
                signal_task = None
            safe_signals.append({
                "kind": signal["kind"],
                "task_id": signal_task,
                "detail": {
                    "success": "development reached integration gate",
                    "repair": "development required repair attempts",
                    "failure": "development failure observed",
                }[signal["kind"]],
            })
        proposal = row.get("proposal")
        safe_proposal = None
        if proposal is not None:
            if not isinstance(proposal, dict):
                raise ValueError("control tower proposal invalid")
            task_hash = proposal.get("task_hash")
            if not isinstance(task_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", task_hash):
                raise ValueError("control tower proposal hash invalid")
            safe_proposal = {
                "task_hash": task_hash,
                "executable": False,
                "approval_required": True,
            }
        safe.append({
            "timestamp": timestamp,
            "task_id": task_id,
            "status": status,
            "exit_code": exit_code,
            "base_sha": base_sha,
            "produced_sha": produced_sha,
            "signals": safe_signals,
            "proposal": safe_proposal,
        })
    return safe[-MAX_RECORDS:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("import", "export"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise SystemExit("durable loop state invalid")
    if args.mode == "import":
        records = sanitize(state.get("control_tower_observations", []))
        args.history.parent.mkdir(parents=True, exist_ok=True)
        temp = args.history.with_name(args.history.name + ".tmp")
        try:
            temp.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in records), encoding="utf-8")
            temp.replace(args.history)
        finally:
            if temp.exists():
                temp.unlink()
        print(f"CONTROL_TOWER_OBSERVATIONS_IMPORTED={len(records)}")
        return 0
    if args.history.exists():
        rows = []
        for line in args.history.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                raise SystemExit("control tower history malformed") from None
        records = sanitize(rows[-MAX_RECORDS:])
    else:
        records = sanitize(state.get("control_tower_observations", []))
    state["control_tower_observations"] = records
    temp = args.state.with_name(args.state.name + ".tmp")
    try:
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(args.state)
    finally:
        if temp.exists():
            temp.unlink()
    print(f"CONTROL_TOWER_OBSERVATIONS_EXPORTED={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
