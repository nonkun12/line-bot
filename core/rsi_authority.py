"""Trusted authority adapters for bounded local RSI experiments.

Approval is tied to the existing authenticated workflow_dispatch contract and is
consumed once through its repository-native marker. During a run, the immutable
dispatch approval is rechecked and the shared emergency STOP is the revocation
mechanism. Recovery AI HOLD is read from its durable aggregate task state.
This module is read-only except for the one-time approval-consumption marker.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def build_rsi_authority(
    *,
    experiment_id: str,
    config_sha256: str,
    start_sha: str,
    instruction: str,
    recovery_state_path: str | Path,
):
    """Build approval and live-safety callbacks for one exact RSI experiment.

    The instruction must include `RSI_EXPERIMENT_ID=<experiment_id>`; this binds
    the human-approved instruction digest to the experiment identity. The caller
    must pass the same immutable start SHA and instruction used by the guarded
    runtime. Any unavailable or mismatched source returns BLOCKED/raises.
    """
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ValueError("rsi_experiment_id_missing")
    if not isinstance(instruction, str):
        raise ValueError("rsi_experiment_not_bound_to_approved_instruction")
    if f"RSI_EXPERIMENT_ID={experiment_id}" not in instruction:
        raise ValueError("rsi_experiment_not_bound_to_approved_instruction")
    if not isinstance(config_sha256, str) or len(config_sha256) != 64 or any(char not in "0123456789abcdef" for char in config_sha256):
        raise ValueError("rsi_experiment_config_digest_invalid")
    if f"RSI_EXPERIMENT_CONFIG_SHA256={config_sha256}" not in instruction:
        raise ValueError("rsi_experiment_config_not_bound_to_approved_instruction")
    if (
        not isinstance(start_sha, str)
        or len(start_sha) != 40
        or any(char not in "0123456789abcdef" for char in start_sha)
    ):
        raise ValueError("rsi_start_sha_invalid")
    if not isinstance(recovery_state_path, (str, Path)) or not str(recovery_state_path).strip():
        raise ValueError("recovery_state_path_missing")

    expected_task_id = os.environ.get("AUTONOMOUS_TASK_ID", "").strip()
    if not expected_task_id:
        raise ValueError("autonomous_task_id_missing")
    consumed = False
    approval_identity: tuple[str, str, str] | None = None

    def approval_verifier(requested_experiment_id: str) -> bool:
        nonlocal consumed, approval_identity
        if requested_experiment_id != experiment_id:
            return False
        if os.environ.get("AUTONOMOUS_TASK_ID", "").strip() != expected_task_id:
            return False
        try:
            from scripts import run_guarded_runtime

            evidence = run_guarded_runtime._verify_execution_approval(start_sha, instruction)
            if (
                not isinstance(evidence, dict)
                or evidence.get("gate") != "PASS"
                or evidence.get("execution_authorized") is not True
                or evidence.get("task_id") != expected_task_id
                or evidence.get("base_sha") != start_sha
            ):
                return False
            identity = (
                str(evidence.get("instruction_sha256", "")),
                str(evidence.get("allowed_paths_sha256", "")),
                str(evidence.get("actor", "")),
            )
            if not all(identity):
                return False
            if approval_identity is not None and identity != approval_identity:
                return False
            if not consumed:
                consumption = run_guarded_runtime._consume_execution_approval(evidence, start_sha)
                if not isinstance(consumption, dict) or consumption.get("gate") != "PASS":
                    return False
                consumed = True
                approval_identity = identity
            return True
        except Exception:
            return False

    def safety_provider() -> dict[str, str]:
        from core.emergency_stop import get_status, local_stop_active
        from scripts.recovery_ai import RecoveryStore

        if local_stop_active(ROOT):
            raise RuntimeError("local_emergency_stop_active")
        repository = (
            os.environ.get("AI_REPORT_GITHUB_REPO")
            or os.environ.get("GITHUB_REPOSITORY")
            or "nonkun12/line-bot"
        ).strip()
        token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
        if not repository or not token:
            raise RuntimeError("shared_stop_credentials_missing")
        if get_status(repository, token):
            raise RuntimeError("shared_emergency_stop_active")

        recovery = RecoveryStore(recovery_state_path)
        hold = recovery.aggregate_hold_status()
        if not isinstance(hold, dict) or hold.get("state") not in {"CLEAR", "ACTIVE"}:
            raise RuntimeError("recovery_hold_state_unconfirmed")
        if hold["state"] != "CLEAR":
            raise RuntimeError("recovery_global_hold_active")

        payload = {
            "stop_state": "INACTIVE",
            "global_hold_state": "CLEAR",
            "recovery_state": hold["state"],
            "recovery_state_updated_at": str(hold.get("state_updated_at") or ""),
            "blocked_task_count": str(len(hold.get("blocked_task_ids", []))),
        }
        return {
            **payload,
            "snapshot_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
        }

    return approval_verifier, safety_provider
