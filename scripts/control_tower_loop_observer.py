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
from core.creator_critic_runtime import build_creator_critic_loop

_MAX_HISTORY = 200
_SAFE_ID = re.compile(r"[^a-zA-Z0-9._-]")


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
    status = _safe_text(outcome.get("status"), 24).upper()
    successful = status in {"PASS", "NO_CHANGE"} and outcome.get("exit_code") == 0
    report = RuntimeReport(
        completed=(),
        failed_task_id=None if successful else (task_id or "unknown_task"),
        error=None if successful else "loop_task_failed",
        rounds=1,
        repair_attempts=0,
        integration_ready=successful,
    )

    # Real-model review is strictly opt-in. Local runners may configure a local
    # OpenAI-compatible endpoint; CI stays model-disabled unless explicitly set.
    creator_critic = (
        build_creator_critic_loop(max_iterations=1)
        if os.environ.get("CREATOR_CRITIC_BASE_URL", "").strip()
        else None
    )
    tower = ControlTower(creator_critic=creator_critic)
    decision = tower.observe(report)
    proposal = decision.proposal
    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "status": status,
        "exit_code": outcome.get("exit_code"),
        "base_sha": _safe_text(outcome.get("base_sha"), 40),
        "produced_sha": _safe_text(outcome.get("produced_sha"), 40),
        "observation_count": len(decision.signals),
        "signals": [
            {
                "kind": _safe_text(signal.kind, 32),
                "task_id": _safe_text(signal.task_id, 128) if signal.task_id else None,
                "detail": _safe_text(signal.detail, 240),
            }
            for signal in decision.signals[:8]
        ],
        "creator_critic": {
            "configured": creator_critic is not None,
            "rounds": len(decision.duel),
            "review_error": decision.review_error,
            "passed": decision.approved_for_pipeline,
            "approved_for_execution": False,
            "feedback": [
                _safe_text(item.evaluation.feedback, 500)
                for item in decision.duel[:1]
            ],
        },
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
