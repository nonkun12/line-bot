"""Bounded durable history for self-improvement signals.

The store is intentionally provider-neutral and append-only. It persists only
structured feedback, never model output or secrets. The caller chooses the
filesystem path, which keeps repository policy outside this module.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

from .self_improvement import ImprovementSignal

_DEFAULT_MAX_RECORDS = 200
_MAX_MAX_RECORDS = 200


class SelfImprovementHistory:
    """Persist a bounded signal history with fail-closed reads."""

    def __init__(self, path: str | Path, *, max_records: int = _DEFAULT_MAX_RECORDS) -> None:
        if max_records < 1 or max_records > _MAX_MAX_RECORDS:
            raise ValueError("max_records must be between 1 and 200")
        self.path = Path(path)
        self.max_records = max_records

    def append(self, signals: Iterable[ImprovementSignal]) -> None:
        """Append validated signals and atomically rewrite the bounded history."""
        records = self._read_records()
        for signal in signals:
            if not isinstance(signal, ImprovementSignal):
                raise TypeError("history entries must be ImprovementSignal")
            records.append(asdict(signal))
        records = records[-self.max_records :]
        self._atomic_write(records)

    def load(self) -> tuple[ImprovementSignal, ...]:
        """Load valid history; malformed records fail closed rather than crash."""
        result: list[ImprovementSignal] = []
        for record in self._read_records():
            try:
                result.append(
                    ImprovementSignal(
                        kind=str(record["kind"]),
                        task_id=None if record.get("task_id") is None else str(record["task_id"]),
                        detail=str(record["detail"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(result)

    def _read_records(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        records: list[dict[str, object]] = []
        for line in lines[-self.max_records :]:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def _atomic_write(self, records: list[dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = None, None
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
                    temp.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            os.replace(temp_name, self.path)
            temp_name = None
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass


__all__ = ["SelfImprovementHistory"]
