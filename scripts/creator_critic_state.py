"""Strict, bounded persistence for sanitized Creator/Critic review records.

This module is intentionally independent of the advisory runner and workflow.
Callers provide the registered task IDs and must validate SHA provenance before
persisting records.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

SCHEMA_VERSION = 1
MAX_RECORDS = 200
MAX_TITLE = 200
MAX_RATIONALE = 1200
_SHA = re.compile(r"^[0-9a-f]{40}$")
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
_STAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
_STATUSES = {"FAIL", "BLOCKED", "TIMEOUT", "STOPPED", "PASS", "NO_CHANGE"}
_REA_GATES = {"PASS", "BLOCKED", "FAIL", "UNKNOWN"}
_RECOVERY_ACTIONS = {"CONTINUE", "REPAIR_ONCE", "HOLD", "STOP", "REVIEW", "UNKNOWN"}
_VERDICTS = {"ACCEPT", "REVISE", "REJECT", "UNAVAILABLE"}
_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,199}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")
_RECORD_FIELDS = {
    "schema_version", "record_id", "run_id", "task_id", "base_sha", "stage",
    "produced_sha", "status", "rea_gate", "recovery_action", "proposal",
    "critic", "created_at", "execution_authorized",
}


def record_id(run_id: str, task_id: str, base_sha: str, stage: str) -> str:
    """Return deterministic identity for one run/task/base/stage tuple."""
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError("invalid run_id")
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise ValueError("invalid task_id")
    if not isinstance(stage, str) or not _STAGE.fullmatch(stage):
        raise ValueError("invalid stage")
    if not _SHA.fullmatch(base_sha):
        raise ValueError("invalid base SHA")
    return hashlib.sha256(f"{run_id}|{task_id}|{base_sha}|{stage}".encode()).hexdigest()


def validate_records(records: object, registered_task_ids: Iterable[str]) -> list[dict[str, object]]:
    """Validate exact schema and provenance; reject the entire input on error."""
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError("invalid Creator/Critic history list or record limit")
    registered = set(registered_task_ids)
    validated: list[dict[str, object]] = []
    for row in records:
        if not isinstance(row, dict) or set(row) != _RECORD_FIELDS:
            raise ValueError("Creator/Critic record schema is invalid")
        if type(row["schema_version"]) is not int or row["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported Creator/Critic schema version")
        rid, run_id_value, task_id, base_sha, stage = (row[k] for k in ("record_id", "run_id", "task_id", "base_sha", "stage"))
        if not isinstance(run_id_value, str) or not _RUN_ID.fullmatch(run_id_value):
            raise ValueError("invalid run_id")
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id) or task_id not in registered:
            raise ValueError("task_id is not registered")
        if not isinstance(base_sha, str) or not _SHA.fullmatch(base_sha):
            raise ValueError("invalid base SHA")
        if not isinstance(stage, str) or not _STAGE.fullmatch(stage):
            raise ValueError("invalid stage")
        produced = row["produced_sha"]
        if produced is not None and (not isinstance(produced, str) or not _SHA.fullmatch(produced)):
            raise ValueError("invalid produced SHA")
        # Missing/malformed produced SHA cannot be asserted as verified evidence.
        if produced is None:
            raise ValueError("produced SHA is required")
        if not isinstance(rid, str) or not re.fullmatch(r"[0-9a-f]{64}", rid):
            raise ValueError("invalid record_id")
        if rid != record_id(run_id_value, task_id, base_sha, stage):
            raise ValueError("record_id does not match record identity")
        if row["status"] not in _STATUSES or row["rea_gate"] not in _REA_GATES or row["recovery_action"] not in _RECOVERY_ACTIONS:
            raise ValueError("invalid status or gate")
        proposal, critic = row["proposal"], row["critic"]
        if not isinstance(proposal, dict) or set(proposal) != {"title", "rationale"}:
            raise ValueError("invalid proposal schema")
        if not isinstance(proposal["title"], str) or not proposal["title"].strip() or len(proposal["title"]) > MAX_TITLE:
            raise ValueError("invalid proposal title")
        if not isinstance(proposal["rationale"], str) or len(proposal["rationale"]) > MAX_RATIONALE:
            raise ValueError("invalid proposal rationale")
        if not isinstance(critic, dict) or set(critic) != {"verdict", "reason_codes", "evidence_refs", "model_id"}:
            raise ValueError("invalid critic schema")
        if critic["verdict"] not in _VERDICTS:
            raise ValueError("invalid critic verdict")
        if not isinstance(critic["reason_codes"], list) or len(critic["reason_codes"]) > 20 or any(not isinstance(x, str) or not _REASON.fullmatch(x) for x in critic["reason_codes"]):
            raise ValueError("invalid critic reason codes")
        if not isinstance(critic["evidence_refs"], list) or len(critic["evidence_refs"]) > 20 or any(not isinstance(x, str) or not _REF.fullmatch(x) for x in critic["evidence_refs"]):
            raise ValueError("invalid critic evidence refs")
        if not isinstance(critic["model_id"], str) or not _MODEL.fullmatch(critic["model_id"]):
            raise ValueError("invalid model id")
        if not isinstance(row["created_at"], str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z", row["created_at"]):
            raise ValueError("created_at must be UTC ISO-8601")
        if row["execution_authorized"] is not False:
            raise ValueError("execution authorization must remain false")
        validated.append(dict(row))
    return validated


def sanitize_records(records: object, registered_task_ids: Iterable[str]) -> list[dict[str, object]]:
    """Validate and return detached records; unsafe fields are rejected."""
    return validate_records(records, registered_task_ids)


def atomic_write(path: str | Path, records: list[dict[str, object]]) -> None:
    """Atomically write a versioned artifact after strict input validation."""
    target = Path(path)
    payload = {"schema_version": SCHEMA_VERSION, "records": records[-MAX_RECORDS:]}
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", delete=False) as temp:
            temp_name = temp.name
            json.dump(payload, temp, ensure_ascii=False, sort_keys=True)
            temp.write("\n")
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_name, target)
        temp_name = None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def read_state(path: str | Path, registered_task_ids: Iterable[str]) -> list[dict[str, object]]:
    """Read versioned state; malformed or corrupt state raises without repair."""
    target = Path(path)
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Creator/Critic state is corrupt or unreadable") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "records"} or type(payload.get("schema_version")) is not int or payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Creator/Critic state envelope is invalid")
    return validate_records(payload["records"], registered_task_ids)


def append_records(path: str | Path, records: object, registered_task_ids: Iterable[str]) -> int:
    """Idempotently append by record_id and retain the newest 200 records."""
    registered = tuple(registered_task_ids)
    additions = validate_records(records, registered)
    current = read_state(path, registered)
    identities = {item["record_id"] for item in current}
    unique_additions = []
    for item in additions:
        identity = item["record_id"]
        if identity not in identities:
            identities.add(identity)
            unique_additions.append(item)
    merged = current + unique_additions
    appended = len(merged) - len(current)
    atomic_write(path, merged[-MAX_RECORDS:])
    return appended


__all__ = ["MAX_RECORDS", "SCHEMA_VERSION", "append_records", "atomic_write", "read_state", "record_id", "sanitize_records", "validate_records"]
