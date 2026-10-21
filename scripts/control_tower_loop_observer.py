"""Durably record bounded post-run observations for the Control Tower.

This adapter is observational only: it never changes task status, executes a
proposal, approves a task, merges, or deploys. The loop outcome remains the
source of truth if observation or persistence fails.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from core.agent_runtime import RuntimeReport
from core.control_tower import ControlTower, task_hash

_MAX_HISTORY = 200
_SAFE_ID = re.compile(r"[^a-zA-Z0-9._-]")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _safe_text(value: object, limit: int = 120) -> str:
    text = str(value or "")
    text = "".join(ch for ch in text if ch.isprintable())
    return text[:limit]


def record_loop_observation(
    history_path: Path,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    """Append one sanitized observation, retaining at most 200 records."""
    task_id = _SAFE_ID.sub("_", _safe_text(outcome.get("task_id"), 128))
    raw_status = outcome.get("status")
    status = _safe_text(raw_status, 24).upper()
    raw_exit_code = outcome.get("exit_code")
    # bool is an int subclass in Python; never accept False as exit code 0.
    exit_code = raw_exit_code if type(raw_exit_code) is int else None
    successful = isinstance(raw_status, str) and raw_status in {"PASS", "NO_CHANGE"} and exit_code == 0
    raw_base_sha = outcome.get("base_sha")
    raw_produced_sha = outcome.get("produced_sha")
    base_sha = raw_base_sha.lower() if isinstance(raw_base_sha, str) and _SHA_RE.fullmatch(raw_base_sha) else None
    produced_sha = raw_produced_sha.lower() if isinstance(raw_produced_sha, str) and _SHA_RE.fullmatch(raw_produced_sha) else None
    report = RuntimeReport(
        completed=(),
        failed_task_id=None if successful else (task_id or "unknown_task"),
        error=None if successful else "loop_task_failed",
        rounds=1,
        repair_attempts=0,
        integration_ready=successful,
    )

    tower = ControlTower()
    decision = tower.observe(report)
    proposal = decision.proposal
    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "status": status,
        "exit_code": exit_code,
        "base_sha": base_sha,
        "produced_sha": produced_sha,
        "observation_count": len(decision.signals),
        "signals": [
            {
                "kind": _safe_text(signal.kind, 32),
                "task_id": _safe_text(signal.task_id, 128) if signal.task_id else None,
                "detail": _safe_text(signal.detail, 240),
            }
            for signal in decision.signals[:8]
        ],
        "proposal": None if proposal is None else {
            "title": _safe_text(proposal.title, 200),
            "rationale": _safe_text(proposal.rationale, 240),
            "task_hash": task_hash(proposal.task),
            "executable": False,
            "approval_required": True,
        },
    }

    history_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    if history_path.exists():
        try:
            for line in history_path.read_text(encoding="utf-8").splitlines()[-(_MAX_HISTORY - 1):]:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    records.append(parsed)
        except (OSError, UnicodeError, json.JSONDecodeError):
            # Fail closed on malformed history; do not overwrite the evidence.
            raise RuntimeError("control_tower_history_unreadable") from None
    records.append(record)
    temp_path = history_path.with_name(history_path.name + ".tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            for item in records[-_MAX_HISTORY:]:
                handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, history_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return {
        "recorded": True,
        "history_count": len(records[-_MAX_HISTORY:]),
        "proposal_available": proposal is not None,
        "proposal_executable": False,
    }


__all__ = ["record_loop_observation"]
