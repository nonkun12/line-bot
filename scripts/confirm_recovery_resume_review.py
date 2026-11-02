"""Confirm one pending Recovery AI resume review in durable loop state."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from scripts.recovery_ai import RecoveryStateError, RecoveryStore


def confirm_in_durable_state(
    state_path: str | Path,
    task_id: str,
    recovery_state_path: str | Path | None = None,
) -> None:
    path = Path(state_path)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryStateError("durable loop state unreadable") from exc
    if not isinstance(state, dict):
        raise RecoveryStateError("durable loop state schema invalid")
    recovery = state.get("recovery_ai")
    if (
        not isinstance(recovery, dict)
        or recovery.get("schema_version") != 1
        or not isinstance(recovery.get("tasks"), dict)
        or "checkpoint" not in recovery
    ):
        raise RecoveryStateError("durable Recovery AI state invalid")

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_recovery = None
    temp_state = None
    temp_local_recovery = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temp_recovery = handle.name
            json.dump(recovery, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        store = RecoveryStore(temp_recovery)
        store.confirm_resume_review(task_id, reviewed=True)
        updated_recovery = json.loads(
            Path(temp_recovery).read_text(encoding="utf-8")
        )
        state["recovery_ai"] = updated_recovery

        if recovery_state_path is not None:
            recovery_path = Path(recovery_state_path)
            try:
                current_recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RecoveryStateError("local Recovery AI state unreadable") from exc
            if current_recovery != recovery:
                raise RecoveryStateError("local and durable Recovery AI state mismatch")
            recovery_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=recovery_path.parent, delete=False
            ) as handle:
                temp_local_recovery = handle.name
                json.dump(updated_recovery, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_local_recovery, recovery_path)
            temp_local_recovery = None

        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temp_state = handle.name
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_state, path)
        temp_state = None

        # Verify the persisted value, not merely the in-memory mutation.
        durable = json.loads(path.read_text(encoding="utf-8"))
        status = durable["recovery_ai"]["tasks"].get(task_id)
        if (
            not isinstance(status, dict)
            or status.get("held") is not False
            or status.get("resume_requires_review") is not False
            or not isinstance(status.get("resume_reviewed_at"), str)
            or not status["resume_reviewed_at"]
        ):
            raise RecoveryStateError("resume review read-back verification failed")
    finally:
        for candidate in (temp_recovery, temp_state, temp_local_recovery):
            if candidate:
                try:
                    os.unlink(candidate)
                except OSError:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--recovery-state-file")
    args = parser.parse_args()
    try:
        confirm_in_durable_state(args.state_file, args.task_id, args.recovery_state_file)
    except (RecoveryStateError, ValueError) as exc:
        print(f"Recovery AI resume review blocked: {type(exc).__name__}")
        return 1
    print("Recovery AI resume review confirmed and durable read-back verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
