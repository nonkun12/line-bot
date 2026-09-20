"""One-time claim ledger for approved self-improvement handoffs.

This ledger is separate from the immutable handoff payload. It records only a
stable fingerprint after an execution layer explicitly claims a handoff, so a
persisted approval cannot be replayed indefinitely after a process restart.
It never executes tasks or grants permissions.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .self_improvement_handoff import ApprovedImprovementHandoff
from .self_improvement_handoff_store import ApprovedImprovementHandoffStore

_DEFAULT_MAX_RECORDS = 200
_MAX_MAX_RECORDS = 1000


class ApprovedImprovementHandoffClaimStore:
    """Persist bounded one-time claims for validated handoffs."""

    def __init__(self, path: str | Path, *, max_records: int = _DEFAULT_MAX_RECORDS) -> None:
        if max_records < 1 or max_records > _MAX_MAX_RECORDS:
            raise ValueError("max_records must be between 1 and 1000")
        self.path = Path(path)
        self.max_records = max_records

    @staticmethod
    def fingerprint(handoff: ApprovedImprovementHandoff) -> str:
        if not isinstance(handoff, ApprovedImprovementHandoff):
            raise TypeError("handoff must be an ApprovedImprovementHandoff")
        payload = {
            "task_hash": handoff.task_hash,
            "allowed_paths": sorted(handoff.allowed_paths),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def claim(self, handoff: ApprovedImprovementHandoff) -> bool:
        """Atomically record a claim; return False when already claimed."""
        # Reuse the original untrusted-input boundary before a claim is recorded.
        ApprovedImprovementHandoffStore._validate_handoff(handoff)
        fingerprint = self.fingerprint(handoff)
        records = self._read()
        if fingerprint in records:
            return False
        records.append(fingerprint)
        self._atomic_write(records[-self.max_records :])
        return True

    def is_claimed(self, handoff: ApprovedImprovementHandoff) -> bool:
        ApprovedImprovementHandoffStore._validate_handoff(handoff)
        return self.fingerprint(handoff) in set(self._read())

    def _read(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        result: list[str] = []
        for line in lines[-self.max_records :]:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value):
                result.append(value)
        return result

    def _atomic_write(self, records: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as temp:
                temp_name = temp.name
                for record in records:
                    temp.write(json.dumps(record) + "\n")
            os.replace(temp_name, self.path)
            temp_name = None
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass


__all__ = ["ApprovedImprovementHandoffClaimStore"]
