"""Fail-closed post-run LoopLab evaluation gate for Distributed Loop.

This stage verifies signed inputs, evaluates supplied predictions, and
records eligible PASS/FAIL observations in the local append-only RSI evidence
ledger. It never runs candidates, invokes a model, changes source/queue state,
clears HOLD/STOP, or authorizes execution/patch/merge/deploy.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

from core.looplab_experiment_adapter import evaluate_simulator_run
from core.looplab_rsi_bridge import record_evaluation_as_rsi_observation
from core.rsi_executor import EvidenceLedger, RSIControl, RSIExecutor

_FORBIDDEN = {
    "execution_authorized": False,
    "patch_authorized": False,
    "hold_clear_authorized": False,
    "stop_clear_authorized": False,
    "merge_deploy_authorized": False,
    "required_human_approval": True,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _blocked(reason: str, experiment_id: str = "") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "BLOCKED",
        "reason": reason,
        "experiment_id": experiment_id,
        "evaluation": None,
        "rsi_ingestion": "NOT_ATTEMPTED_TRUSTED_RUNTIME_REQUIRED",
        "authority": dict(_FORBIDDEN),
    }


def _key(env: Mapping[str, str], name: str) -> bytes:
    value = env.get(name, "")
    if not isinstance(value, str) or len(value.encode("utf-8")) < 32:
        raise ValueError("trusted_key_missing_or_too_short:" + name.lower())
    return value.encode("utf-8")


def _read_json(path: Path, reason: str) -> Any:
    if not path.is_file():
        raise ValueError(reason)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError(reason + "_invalid") from None


def _read_signed_payload(path: Path, key: bytes, reason: str) -> dict[str, Any]:
    envelope = _read_json(path, reason)
    if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
        raise ValueError(reason + "_schema_invalid")
    signature = envelope.get("signature")
    if not isinstance(signature, str) or len(signature) != 64:
        raise ValueError(reason + "_signature_missing")
    expected = hmac.new(key, _canonical(envelope["payload"]), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError(reason + "_signature_invalid")
    return envelope["payload"]


def evaluate_postrun(
    *,
    simulator_path: str | Path,
    dataset_path: str | Path,
    registry_path: str | Path,
    safety_path: str | Path,
    output_path: str | Path,
    env: Mapping[str, str] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Evaluate only authenticated artifacts; every missing trust input is BLOCKED."""
    env = os.environ if env is None else env
    now = int(time.time()) if now is None else now
    result: dict[str, Any]
    try:
        simulator_key = _key(env, "LOOPLAB_SIMULATOR_HMAC_KEY")
        registry_key = _key(env, "LOOPLAB_DATASET_REGISTRY_HMAC_KEY")
        safety_key = _key(env, "LOOPLAB_SAFETY_HMAC_KEY")
        adapter_key = _key(env, "LOOPLAB_ADAPTER_HMAC_KEY")
        evidence_key = _key(env, "LOOPLAB_RSI_EVIDENCE_HMAC_KEY")

        simulator = _read_signed_payload(Path(simulator_path), simulator_key, "simulator_artifact")
        registry = _read_signed_payload(Path(registry_path), registry_key, "dataset_registry")
        safety = _read_signed_payload(Path(safety_path), safety_key, "safety_snapshot")
        dataset = _read_json(Path(dataset_path), "held_out_dataset")

        experiment_id = simulator.get("experiment_id", "")
        if not isinstance(experiment_id, str) or not experiment_id.strip() or len(experiment_id) > 100:
            raise ValueError("experiment_id_invalid")
        if not isinstance(dataset, list) or not dataset:
            raise ValueError("held_out_dataset_empty_or_invalid")
        if not isinstance(registry.get("datasets"), dict):
            raise ValueError("dataset_registry_schema_invalid")

        dataset_digest = hashlib.sha256(_canonical(dataset)).hexdigest()
        dataset_id = experiment_id + ":held-out"
        entry = registry["datasets"].get(dataset_id)
        if not isinstance(entry, dict):
            raise ValueError("held_out_dataset_not_registered")
        sample_count = len(dataset)
        if (
            entry.get("locked") is not True
            or entry.get("dataset_sha256") != dataset_digest
            or entry.get("sample_count") != sample_count
            or type(entry.get("minimum_sample_count")) is not int
            or entry["minimum_sample_count"] < 1
            or sample_count < entry["minimum_sample_count"]
        ):
            raise ValueError("held_out_dataset_registry_mismatch")

        issued_at = safety.get("issued_at")
        expires_at = safety.get("expires_at")
        if (
            type(issued_at) is not int
            or type(expires_at) is not int
            or issued_at > now + 30
            or expires_at <= now
            or expires_at <= issued_at
            or expires_at - issued_at > 300
        ):
            raise ValueError("safety_snapshot_stale_or_invalid")
        if safety.get("stop_state") != "INACTIVE":
            raise ValueError("stop_active_or_unverified")
        if safety.get("global_hold_state") != "CLEAR":
            raise ValueError("global_hold_active_or_unverified")
        if (safety.get("execution_enabled") is not False
                or safety.get("free_only") is not True
                or safety.get("budget_known") is not True
                or safety.get("paid_fallback_enabled") is not False
                or type(safety.get("budget_remaining_units")) is not int
                or not 1 <= safety["budget_remaining_units"] <= 1_000_000):
            raise ValueError("rsi_control_snapshot_missing_or_unsafe")

        evaluated = evaluate_simulator_run(
            simulator_output=simulator,
            held_out_dataset=dataset,
            held_out_locked=True,
            held_out_expected_sha256=dataset_digest,
            safety={
                "stop_state": safety["stop_state"],
                "global_hold_state": safety["global_hold_state"],
            },
            minimum_delta=0.0,
            sign_adapter_digest=lambda adapter_id, digest: hmac.new(
                adapter_key, (adapter_id + ":" + digest).encode("utf-8"), hashlib.sha256
            ).hexdigest(),
        )
        status = evaluated.get("status")
        if status not in {"PASS", "FAIL"}:
            result = _blocked(
                str((evaluated.get("evaluation") or {}).get("reason") or "simulator_evaluation_blocked")[:120],
                experiment_id,
            )
            result["evaluation"] = evaluated
        else:
            ledger_path = Path(output_path).with_name("looplab-rsi-evidence.sqlite")
            ledger = EvidenceLedger(ledger_path)
            safety_state = {
                "stop_state": safety["stop_state"],
                "global_hold_state": safety["global_hold_state"],
            }
            registry_entry = dict(entry)

            def _sign_evidence(digest: str) -> str:
                return hmac.new(evidence_key, digest.encode("ascii"), hashlib.sha256).hexdigest()

            def _verify_evidence(producer_id: str, digest: str, signature: str) -> bool:
                expected = _sign_evidence(digest)
                return (
                    producer_id == "looplab-independent-evaluator"
                    and isinstance(signature, str)
                    and hmac.compare_digest(signature, expected)
                )

            def _verify_adapter(adapter_id: str, digest: str, signature: str) -> bool:
                expected = hmac.new(
                    adapter_key, (adapter_id + ":" + digest).encode("utf-8"), hashlib.sha256
                ).hexdigest()
                return (
                    adapter_id == "looplab.simulator_rsi_bridge.v1"
                    and isinstance(signature, str)
                    and hmac.compare_digest(signature, expected)
                )

            executor = RSIExecutor(
                ledger,
                control_provider=lambda: RSIControl(
                    global_hold=False,
                    execution_enabled=False,
                    free_only=True,
                    budget_known=True,
                    budget_remaining_units=safety["budget_remaining_units"],
                    paid_fallback_enabled=False,
                ),
                verify_approval=lambda _approval: False,
                verify_evaluation=lambda _evaluation: False,
                verify_evidence_signature=_verify_evidence,
                executor_id="looplab-postrun-bridge",
                verify_adapter_signature=_verify_adapter,
                resolve_locked_dataset=lambda requested_id: (
                    registry_entry if requested_id == dataset_id else None
                ),
                safety_state_provider=lambda: dict(safety_state),
            )
            try:
                ingestion = record_evaluation_as_rsi_observation(
                    evaluation_result=evaluated,
                    executor=executor,
                    producer_id="looplab-independent-evaluator",
                    sign_digest=_sign_evidence,
                    created_at=now,
                )
                ingestion_status = "RECORDED" if ingestion.get("recorded") is True else "BLOCKED"
                ingestion_reason = ingestion.get("reason", "")
            except (TypeError, ValueError, OverflowError) as exc:
                ingestion = None
                ingestion_status = "BLOCKED"
                ingestion_reason = type(exc).__name__
            result = {
                "schema_version": 1,
                "status": status,
                "reason": str((evaluated.get("evaluation") or {}).get("reason") or status)[:120],
                "experiment_id": experiment_id,
                "evaluation": evaluated,
                "rsi_ingestion": ingestion_status,
                "rsi_ingestion_reason": ingestion_reason,
                "rsi": ingestion,
                "rsi_ledger": str(ledger_path) if ingestion_status == "RECORDED" else None,
                "authority": dict(_FORBIDDEN),
            }
    except (OSError, TypeError, ValueError, OverflowError) as exc:
        reason = str(exc).split(":", 1)[0][:120] or type(exc).__name__
        result = _blocked(reason)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulator", default="/tmp/looplab-simulator-output.json")
    parser.add_argument("--dataset", default="/tmp/looplab-held-out-dataset.json")
    parser.add_argument("--registry", default="/tmp/looplab-dataset-registry.json")
    parser.add_argument("--safety", default="/tmp/looplab-safety-snapshot.json")
    parser.add_argument("--output", default="/tmp/looplab-postrun-result.json")
    args = parser.parse_args()
    result = evaluate_postrun(
        simulator_path=args.simulator,
        dataset_path=args.dataset,
        registry_path=args.registry,
        safety_path=args.safety,
        output_path=args.output,
    )
    print(json.dumps({
        "status": result["status"],
        "reason": result["reason"],
        "experiment_id": result["experiment_id"],
        "rsi_ingestion": result["rsi_ingestion"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
