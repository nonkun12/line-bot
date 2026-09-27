"""Bounded durable history for self-improvement signals and cycle memory.

The store is provider-neutral and append-only. It persists structured feedback
and bounded cycle outcomes, never model output or secrets. The caller chooses
the filesystem path, which keeps repository policy outside this module.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

from .self_improvement import ImprovementSignal

_DEFAULT_MAX_RECORDS = 200
_MAX_MAX_RECORDS = 200
_MAX_MEMORY_TEXT = 1200


@dataclass(frozen=True)
class SelfImprovementMemoryRecord:
    """One bounded outcome -> cause -> improvement -> next-action memory entry."""

    outcome: str
    cause: str
    improvements: tuple[str, ...]
    next_action: str
    target_path: str = ""
    recurring_patterns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.outcome not in {"PASS", "FAIL", "BLOCKED"}:
            raise ValueError("invalid memory outcome")
        for value in (self.cause, self.next_action, self.target_path):
            if len(str(value)) > _MAX_MEMORY_TEXT:
                raise ValueError("memory field exceeds bounded length")
        if len(self.improvements) > 3 or len(self.recurring_patterns) > 5:
            raise ValueError("memory list exceeds bounded length")
        if any(len(str(value)) > _MAX_MEMORY_TEXT for value in (*self.improvements, *self.recurring_patterns)):
            raise ValueError("memory list item exceeds bounded length")


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
        self._atomic_write(records)

    def append_memory(self, memory: SelfImprovementMemoryRecord) -> None:
        """Append one bounded cycle memory entry without changing signal semantics."""
        if not isinstance(memory, SelfImprovementMemoryRecord):
            raise TypeError("memory must be SelfImprovementMemoryRecord")
        records = self._read_records()
        records.append({"record_type": "cycle_memory", **asdict(memory)})
        self._atomic_write(records)

    def load(self) -> tuple[ImprovementSignal, ...]:
        """Load valid signal history; malformed records fail closed."""
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

    def load_memory(self, *, limit: int = 5) -> tuple[SelfImprovementMemoryRecord, ...]:
        """Load the newest bounded cycle memories; malformed records are ignored."""
        if limit < 1 or limit > 20:
            raise ValueError("limit must be between 1 and 20")
        result: list[SelfImprovementMemoryRecord] = []
        for record in self._read_records():
            if record.get("record_type") != "cycle_memory":
                continue
            try:
                result.append(
                    SelfImprovementMemoryRecord(
                        outcome=str(record["outcome"]),
                        cause=str(record.get("cause", ""))[:_MAX_MEMORY_TEXT],
                        improvements=tuple(str(value)[:_MAX_MEMORY_TEXT] for value in record.get("improvements", ())),
                        next_action=str(record["next_action"])[:_MAX_MEMORY_TEXT],
                        target_path=str(record.get("target_path", ""))[:_MAX_MEMORY_TEXT],
                        recurring_patterns=tuple(str(value)[:_MAX_MEMORY_TEXT] for value in record.get("recurring_patterns", ())),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(result[-limit:])

    def _read_records(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        records: list[dict[str, object]] = []
        for line in lines[-self.max_records:]:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records[-self.max_records:]

    def _atomic_write(self, records: list[dict[str, object]]) -> None:
        records = records[-self.max_records:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
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
                    temp.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "
")
            os.replace(temp_name, self.path)
            temp_name = None
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass


__all__ = ["SelfImprovementHistory", "SelfImprovementMemoryRecord"]
