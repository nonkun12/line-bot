"""Explicit, append-only JSONL persistence for Idea AI experiment evidence.

Writes are opt-in function calls. The store never starts experiments or grants
verification; it only persists already-constructed evidence records.
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
from pathlib import Path

from core.idea_evidence import ExperimentEvidence

_MAX_RECORDS = 500
_MAX_STORE_BYTES = 1_048_576
_MAX_LINE_BYTES = 8_192


def _open_store(path: str | os.PathLike[str], flags: int) -> int:
    target = Path(path)
    if not target.name:
        raise ValueError("store path must name a file")
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("safe no-follow file access is unavailable")
    try:
        fd = os.open(target, flags | os.O_NOFOLLOW, 0o600)
    except FileNotFoundError:
        raise
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise ValueError("evidence store must be a regular file")
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        raise PermissionError("evidence store permissions must be 0600")
    if info.st_size > _MAX_STORE_BYTES:
        os.close(fd)
        raise ValueError("evidence store exceeds size limit")
    return fd


def _decode_records(raw: bytes) -> tuple[ExperimentEvidence, ...]:
    if not raw:
        return ()
    records: list[ExperimentEvidence] = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line or len(line) > _MAX_LINE_BYTES:
            raise ValueError(f"invalid evidence record line {line_number}")
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("record must be a JSON object")
            records.append(ExperimentEvidence(**payload))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"invalid evidence record line {line_number}") from exc
    if len(records) > _MAX_RECORDS:
        raise ValueError("evidence store exceeds record limit")
    ids = [record.experiment_id for record in records]
    if len(set(ids)) != len(ids):
        raise ValueError("evidence store contains duplicate experiment IDs")
    return tuple(records)


def load_evidence_records(path: str | os.PathLike[str]) -> tuple[ExperimentEvidence, ...]:
    """Load and validate a private, regular JSONL evidence file."""
    fd = _open_store(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        raw = os.read(fd, _MAX_STORE_BYTES + 1)
        if len(raw) > _MAX_STORE_BYTES:
            raise ValueError("evidence store exceeds size limit")
        return _decode_records(raw)
    finally:
        os.close(fd)


def append_evidence_record(
    path: str | os.PathLike[str],
    record: ExperimentEvidence,
) -> tuple[ExperimentEvidence, ...]:
    """Append one validated record under an exclusive lock and fsync it.

    Parent directories must already exist. Existing files must be regular and
    private (0600); symlinks and non-regular files fail closed.
    """
    if not isinstance(record, ExperimentEvidence):
        raise TypeError("record must be an ExperimentEvidence value")
    fd = _open_store(path, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, _MAX_STORE_BYTES + 1)
        if len(raw) > _MAX_STORE_BYTES:
            raise ValueError("evidence store exceeds size limit")
        existing = _decode_records(raw)
        if len(existing) >= _MAX_RECORDS:
            raise ValueError("evidence store record limit reached")
        if any(item.experiment_id == record.experiment_id for item in existing):
            raise ValueError("experiment_id already exists")
        line = (json.dumps(record.__dict__, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(line) > _MAX_LINE_BYTES:
            raise ValueError("serialized evidence record exceeds line limit")
        if len(raw) + len(line) > _MAX_STORE_BYTES:
            raise ValueError("evidence store size limit reached")
        os.lseek(fd, 0, os.SEEK_END)
        remaining = memoryview(line)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("short write to evidence store")
            remaining = remaining[written:]
        os.fsync(fd)
        return existing + (record,)
    finally:
        os.close(fd)


__all__ = ["append_evidence_record", "load_evidence_records"]
