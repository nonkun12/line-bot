"""Bounded local Mac executor for explicitly typed audiovisual Goal jobs.

This module is intentionally separate from the GitHub Actions code-edit worker.
It accepts no shell commands, arbitrary paths, downloads, or publish actions.
The caller must supply a claimed Goal child and an explicit local output root.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from agents.media.production import create_audiovisual_production_bundle

EXECUTOR_ID = "mac_local_media.v1"
OPERATION = "create_audiovisual_bundle"
_JOB_ID = re.compile(r"^[1-9][0-9]{0,17}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_ARTIFACT_FILENAMES = {
    "scenario": "scenario.json",
    "storyboard": "storyboard.json",
    "shot_list": "shot_list.json",
    "music_plan": "music_plan.json",
    "midi": "original_music.mid",
    "audio_preview": "original_music.wav",
    "video_edit_decision_list": "edit_decision_list.json",
    "video": "final_video.mp4",
}
_REQUIRED_ARTIFACTS = set(_ARTIFACT_FILENAMES) - {"video"}


def _output_from_existing_receipt(receipt_path: Path, destination: Path, job_id: int) -> dict[str, Any]:
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise RuntimeError("existing media output has no safe receipt; keep the Goal job on HOLD")
    receipt_bytes = receipt_path.read_bytes()
    try:
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("existing media receipt is invalid; keep the Goal job on HOLD") from exc
    hashes = receipt.get("artifact_sha256") if isinstance(receipt, dict) else None
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != "mac-local-media-receipt.v1"
        or receipt.get("executor") != EXECUTOR_ID
        or receipt.get("operation") != OPERATION
        or receipt.get("goal_job_id") != job_id
        or receipt.get("idempotency_key") != hashlib.sha256(f"{EXECUTOR_ID}:{job_id}".encode()).hexdigest()
        or receipt.get("status") != "draft"
        or receipt.get("publication") != "not_performed"
        or not isinstance(hashes, dict)
        or set(hashes) != _REQUIRED_ARTIFACTS
        or receipt.get("video_render_status") != "not_rendered"
    ):
        raise RuntimeError("existing media receipt does not match this Goal job; keep it on HOLD")
    for logical_name, expected_hash in hashes.items():
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise RuntimeError("existing media receipt contains an invalid artifact hash")
        artifact = destination / _ARTIFACT_FILENAMES[logical_name]
        if artifact.is_symlink() or not artifact.is_file() or _sha256(artifact) != expected_hash:
            raise RuntimeError("existing media artifact failed integrity verification; keep it on HOLD")
    receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()
    result = receipt_bytes.decode("utf-8").rstrip("\n")
    evidence = {
        "checks": [
            {"name": "typed_local_executor_authorization", "status": "PASS", "source": EXECUTOR_ID},
            {"name": "scenario_validation", "status": "PASS", "source": EXECUTOR_ID},
            {"name": "output_confined_to_configured_root", "status": "PASS", "source": EXECUTOR_ID},
            {"name": "artifact_inventory_and_sha256", "status": "PASS", "source": EXECUTOR_ID},
            {"name": "no_publish_or_external_download", "status": "PASS", "source": EXECUTOR_ID},
        ],
        "executor": EXECUTOR_ID,
        "goal_job_id": job_id,
        "output_directory": str(destination),
        "artifact_sha256": hashes,
        "receipt_sha256": receipt_hash,
        "video_render_status": receipt.get("video_render_status", "not_rendered"),
    }
    return {"result": result, "evidence": evidence}


def execute_local_media_job(
    job: dict[str, Any],
    payload: dict[str, Any],
    *,
    output_root: str | Path | None = None,
    bundle_creator: Callable[..., dict[str, Any]] = create_audiovisual_production_bundle,
) -> dict[str, Any]:
    """Create one local-only media bundle from a claimed, typed Goal child.

    Required payload:
      executor: "mac_local_media.v1"
      operation: "create_audiovisual_bundle"
      scenario: validated video-scenario.v1 object

    Output location is derived from the numeric job ID under output_root.
    Payload-supplied paths and commands are never used.
    """
    if not isinstance(job, dict) or job.get("job_type") != "goal_child":
        raise PermissionError("only typed Goal child jobs may use the local media executor")
    job_id = job.get("id")
    if type(job_id) is not int or not _JOB_ID.fullmatch(str(job_id)):
        raise ValueError("Goal child job ID is invalid")
    claim_token = job.get("claim_token")
    if not isinstance(claim_token, str) or len(claim_token) < 20:
        raise PermissionError("a claimed Goal child token is required")
    if not isinstance(payload, dict):
        raise ValueError("local media payload must be an object")
    if payload.get("executor") != EXECUTOR_ID or payload.get("operation") != OPERATION:
        raise PermissionError("Goal child is not explicitly assigned to the local media executor")

    scenario = payload.get("scenario")
    from agents.video.scenario import validate_scenario

    errors = validate_scenario(scenario)
    if errors:
        raise ValueError("invalid production scenario: " + ", ".join(errors))

    root_value = output_root or os.environ.get("LOCAL_MEDIA_OUTPUT_ROOT")
    if not isinstance(root_value, (str, Path)) or not str(root_value).strip():
        raise RuntimeError("LOCAL_MEDIA_OUTPUT_ROOT is not configured; keep the job on HOLD")
    root = Path(root_value).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = (root / f"goal-child-{job_id}").resolve()
    if destination.parent != root:
        raise PermissionError("derived output path escaped the configured root")

    receipt_path = destination / "executor_receipt.json"
    if destination.exists():
        return _output_from_existing_receipt(receipt_path, destination, job_id)

    # The bundle creator creates a new directory exclusively. A partial or
    # pre-existing output is never overwritten; retries only reuse a verified receipt.
    result = bundle_creator(scenario, destination, bpm=120)
    if not isinstance(result, dict) or result.get("status") != "draft_bundle_created":
        raise RuntimeError("media bundle creator did not return a successful draft receipt")

    artifact_names = result.get("artifacts")
    if not isinstance(artifact_names, dict) or not artifact_names:
        raise RuntimeError("media bundle has no artifact inventory")
    artifact_hashes: dict[str, str] = {}
    for logical_name, relative_name in sorted(artifact_names.items()):
        if not isinstance(logical_name, str) or not isinstance(relative_name, str):
            raise RuntimeError("media artifact inventory is malformed")
        relative_path = Path(relative_name)
        if relative_path.name != relative_name or relative_path.is_absolute():
            raise RuntimeError("media artifact names must be flat filenames")
        candidate = destination / relative_path
        if candidate.is_symlink():
            raise RuntimeError("symbolic-link artifacts are not accepted")
        artifact = candidate.resolve()
        if artifact.parent != destination or not artifact.is_file():
            raise RuntimeError("media artifact is missing or escaped the bundle directory")
        artifact_hashes[logical_name] = _sha256(artifact)

    receipt = {
        "schema_version": "mac-local-media-receipt.v1",
        "executor": EXECUTOR_ID,
        "operation": OPERATION,
        "goal_job_id": job_id,
        "idempotency_key": hashlib.sha256(f"{EXECUTOR_ID}:{job_id}".encode()).hexdigest(),
        "status": "draft",
        "artifact_sha256": artifact_hashes,
        "video_render_status": result.get("video_render_status", "not_rendered"),
        "publication": "not_performed",
    }
    receipt_json = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with receipt_path.open("x", encoding="utf-8") as stream:
        stream.write(receipt_json + "\n")
    return _output_from_existing_receipt(receipt_path, destination, job_id)


__all__ = ["EXECUTOR_ID", "OPERATION", "execute_local_media_job"]
