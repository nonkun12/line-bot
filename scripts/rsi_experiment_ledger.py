"""Append-only, hash-chained local ledger for RSI experiment evidence.

No network access, candidate execution, or authority changes are performed here.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_ZERO_HASH = "0" * 64
_SENSITIVE_KEY = re.compile(
    r"(^|_)(api_key|access_token|refresh_token|github_token|"
    r"line_channel_access_token|password|secret|authorization|cookie|"
    r"webhook_url|private_key|client_secret|credential|credentials)($|_)",
    re.IGNORECASE,
)


def _reject_secret_fields(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("ledger_payload_key_must_be_string")
            if _SENSITIVE_KEY.search(key):
                raise ValueError(f"ledger_sensitive_field_rejected:{path}.{key}")
            _reject_secret_fields(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_secret_fields(child, f"{path}[{index}]")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def verify_ledger(path: str | Path) -> list[dict[str, Any]]:
    """Return verified entries; raise ValueError on any gap or tampering."""
    ledger_path = Path(path)
    if not ledger_path.exists():
        return []

    entries: list[dict[str, Any]] = []
    previous = _ZERO_HASH
    expected_sequence = 1
    with ledger_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                raise ValueError(f"ledger_blank_line:{line_number}")
            try:
                envelope = json.loads(line)
            except json.JSONDecodeError:
                raise ValueError(f"ledger_invalid_json:{line_number}") from None
            if not isinstance(envelope, dict):
                raise ValueError(f"ledger_entry_not_object:{line_number}")

            sequence = envelope.get("sequence")
            previous_hash = envelope.get("previous_sha256")
            payload = envelope.get("payload")
            claimed_hash = envelope.get("entry_sha256")
            if (
                not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence != expected_sequence
                or previous_hash != previous
                or not isinstance(payload, dict)
                or not isinstance(claimed_hash, str)
            ):
                raise ValueError(f"ledger_chain_invalid:{line_number}")

            unsigned = {
                "sequence": sequence,
                "previous_sha256": previous_hash,
                "payload": payload,
            }
            actual_hash = _digest(unsigned)
            if actual_hash != claimed_hash:
                raise ValueError(f"ledger_digest_mismatch:{line_number}")

            entries.append({
                **unsigned,
                "entry_sha256": actual_hash,
            })
            previous = actual_hash
            expected_sequence += 1
    return entries


def append_ledger_entry(path: str | Path, payload: Mapping[str, Any]) -> str:
    """Append one payload under an exclusive file lock and return its digest."""
    if not isinstance(payload, Mapping):
        raise TypeError("ledger_payload_must_be_object")
    safe_payload = dict(payload)
    # Refuse obvious credential-bearing fields before opening or mutating.
    _reject_secret_fields(safe_payload)
    # Validate serializability before opening or mutating the ledger.
    _canonical(safe_payload)

    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            stream.seek(0)
            existing = verify_ledger(ledger_path)
            previous = existing[-1]["entry_sha256"] if existing else _ZERO_HASH
            unsigned = {
                "sequence": len(existing) + 1,
                "previous_sha256": previous,
                "payload": safe_payload,
            }
            entry_hash = _digest(unsigned)
            envelope = {**unsigned, "entry_sha256": entry_hash}
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(
                envelope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            return entry_hash
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
