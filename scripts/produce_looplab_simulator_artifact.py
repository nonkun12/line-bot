"""Create a run-bound, signed LoopLab Simulator artifact from supplied predictions.

This producer never runs a model. Predictions must be supplied by an independently
authorized local inference process. Trust registry and safety inputs remain external.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_PRODUCER_ID = "distributed-loop-simulator-producer.v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("input_json_unavailable_or_invalid:" + path.name) from None


def sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("candidate_artifact_missing_or_not_regular_file:" + path.name)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _predictions(path: Path, expected_ids: set[str]) -> list[dict[str, str]]:
    rows = read_json(path)
    if not isinstance(rows, list) or len(rows) != len(expected_ids):
        raise ValueError("prediction_coverage_incomplete:" + path.name)
    seen: set[str] = set()
    normalized: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("prediction_row_invalid:" + path.name)
        sample_id, output = row.get("sample_id"), row.get("output")
        if (not isinstance(sample_id, str) or not sample_id.strip()
                or not isinstance(output, str) or not output.strip()
                or len(output) > 100_000):
            raise ValueError("prediction_schema_invalid:" + path.name)
        if sample_id in seen:
            raise ValueError("prediction_sample_duplicate:" + path.name)
        seen.add(sample_id)
        normalized.append({"sample_id": sample_id, "output": output})
    if seen != expected_ids:
        raise ValueError("prediction_dataset_mismatch:" + path.name)
    return normalized


def build_payload(
    *, dataset_path: Path, baseline_predictions_path: Path,
    challenger_predictions_path: Path, baseline_artifact_path: Path,
    challenger_artifact_path: Path, experiment_id: str,
    run_id: str, commit_sha: str, created_at: int | None = None,
) -> dict[str, Any]:
    if not isinstance(experiment_id, str) or not experiment_id.strip() or len(experiment_id) > 100:
        raise ValueError("experiment_id_invalid")
    if not isinstance(run_id, str) or not run_id.isdigit():
        raise ValueError("github_run_id_missing_or_invalid")
    if not isinstance(commit_sha, str) or not (_SHA40.fullmatch(commit_sha) or _SHA64.fullmatch(commit_sha)):
        raise ValueError("github_commit_sha_missing_or_invalid")
    dataset = read_json(dataset_path)
    if not isinstance(dataset, list) or not dataset:
        raise ValueError("held_out_dataset_empty_or_invalid")
    sample_ids = []
    for row in dataset:
        if not isinstance(row, dict) or not isinstance(row.get("sample_id"), str) or not row["sample_id"].strip():
            raise ValueError("held_out_dataset_row_invalid")
        sample_ids.append(row["sample_id"])
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("held_out_dataset_sample_ids_duplicate")
    expected_ids = set(sample_ids)
    baseline = {
        "candidate_id": "baseline:" + sha256_file(baseline_artifact_path)[:16],
        "artifact_sha256": sha256_file(baseline_artifact_path),
        "predictions": _predictions(baseline_predictions_path, expected_ids),
    }
    challenger = {
        "candidate_id": "challenger:" + sha256_file(challenger_artifact_path)[:16],
        "artifact_sha256": sha256_file(challenger_artifact_path),
        "predictions": _predictions(challenger_predictions_path, expected_ids),
    }
    if baseline["candidate_id"] == challenger["candidate_id"]:
        raise ValueError("candidate_artifacts_must_be_distinct")
    return {
        "schema_version": 1,
        "producer_id": _PRODUCER_ID,
        "experiment_id": experiment_id,
        "dataset_id": experiment_id + ":held-out",
        "dataset_sha256": hashlib.sha256(canonical(dataset)).hexdigest(),
        "source_run_id": run_id,
        "source_commit_sha": commit_sha,
        "created_at": int(time.time()) if created_at is None else created_at,
        "baseline": baseline,
        "challenger": challenger,
    }


def write_signed_artifact(payload: dict[str, Any], output_path: Path, key: bytes) -> None:
    if len(key) < 32:
        raise ValueError("simulator_signing_key_missing_or_too_short")
    envelope = {
        "payload": payload,
        "signature": hmac.new(key, canonical(payload), hashlib.sha256).hexdigest(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".looplab-simulator-", dir=str(output_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(envelope, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output_path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--baseline-predictions", required=True)
    parser.add_argument("--challenger-predictions", required=True)
    parser.add_argument("--baseline-artifact", required=True)
    parser.add_argument("--challenger-artifact", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--output", default="/tmp/looplab-simulator-output.json")
    args = parser.parse_args()
    key_text = os.environ.get("LOOPLAB_SIMULATOR_HMAC_KEY", "")
    if len(key_text.encode("utf-8")) < 32:
        print("BLOCKED: simulator_signing_key_missing_or_too_short", file=sys.stderr)
        return 2
    try:
        payload = build_payload(
            dataset_path=Path(args.dataset),
            baseline_predictions_path=Path(args.baseline_predictions),
            challenger_predictions_path=Path(args.challenger_predictions),
            baseline_artifact_path=Path(args.baseline_artifact),
            challenger_artifact_path=Path(args.challenger_artifact),
            experiment_id=args.experiment_id,
            run_id=os.environ.get("GITHUB_RUN_ID", ""),
            commit_sha=os.environ.get("GITHUB_SHA", ""),
        )
        write_signed_artifact(payload, Path(args.output), key_text.encode("utf-8"))
    except (OSError, ValueError) as exc:
        print("BLOCKED: " + str(exc)[:200], file=sys.stderr)
        return 2
    print(json.dumps({
        "status": "ARTIFACT_CREATED",
        "producer_id": _PRODUCER_ID,
        "experiment_id": payload["experiment_id"],
        "sample_count": len(payload["baseline"]["predictions"]),
        "source_run_id": payload["source_run_id"],
        "source_commit_sha": payload["source_commit_sha"],
        "output": args.output,
        "signature_created": True,
        "trust_registry_created": False,
        "safety_snapshot_created": False,
        "model_execution_performed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
