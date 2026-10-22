"""Bounded durable history for self-improvement signals and cycle memory.

The store is provider-neutral and append-only. It persists structured feedback
and bounded cycle outcomes, never model output or secrets. The caller chooses
the filesystem path, which keeps repository policy outside this module.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

from .self_improvement import ImprovementSignal

_DEFAULT_MAX_RECORDS = 200
_MAX_MAX_RECORDS = 200
_MAX_MEMORY_TEXT = 1200
_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SENSITIVE_TASK_ID = re.compile(r"(?i)^(?:sk-[a-z0-9_-]{8,}|gh[pousr]_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,})$")
_SAFE_RELATIVE_PATH = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")
_SAFE_SIGNAL_DETAILS = {
    "success": "development reached integration gate",
    "repair": "development required repair attempts",
    "failure": "development failure observed",
}


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
            if signal.kind not in _SAFE_SIGNAL_DETAILS:
                raise ValueError("unsupported self-improvement signal kind")
            task_id = signal.task_id
            if task_id is not None and (
                not _SAFE_TASK_ID.fullmatch(task_id)
                or _SENSITIVE_TASK_ID.fullmatch(task_id)
            ):
                task_id = None
            # Do not persist report.error or any model/user-controlled detail.
            records.append({
                "kind": signal.kind,
                "task_id": task_id,
                "detail": _SAFE_SIGNAL_DETAILS[signal.kind],
            })
        self._atomic_write(records)

    def append_memory(self, memory: SelfImprovementMemoryRecord) -> None:
        """Append one bounded cycle memory entry without changing signal semantics."""
        if not isinstance(memory, SelfImprovementMemoryRecord):
            raise TypeError("memory must be SelfImprovementMemoryRecord")
        records = self._read_records()
        target_paths = [
            part.strip()
            for part in memory.target_path.split(",")
            if part.strip()
        ]
        safe_target_path = ", ".join(
            path for path in target_paths
            if _SAFE_RELATIVE_PATH.fullmatch(path)
            and all(part not in {".", ".."} for part in path.split("/"))
        )[:_MAX_MEMORY_TEXT]
        # Free-form error/proposal text can contain credentials or prompt content.
        # Keep only bounded categorical metadata in durable history.
        records.append({
            "record_type": "cycle_memory",
            "outcome": memory.outcome,
            "cause": {
                "PASS": "development gate passed",
                "FAIL": "development gate failed",
                "BLOCKED": "development gate blocked",
            }[memory.outcome],
            "improvements": ["improvement proposal recorded"] * min(len(memory.improvements), 3),
            "next_action": "review outcome before execution",
            "target_path": safe_target_path,
            # Pattern keys can contain raw exception messages; discard until a
            # dedicated non-sensitive pattern identifier is used.
            "recurring_patterns": [],
        })
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
        # Never treat an unreadable existing history as empty: append() would
        # otherwise replace it with a truncated history and silently lose memory.
        # Propagate I/O errors so callers fail closed before any write occurs.
        lines = self.path.read_text(encoding="utf-8").splitlines()
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
        # Re-sanitize every existing record as well as new entries. This also
        # removes sensitive data left by versions that wrote raw errors.
        records = [
            safe for record in records
            if (safe := _sanitize_history_record(record)) is not None
        ][-self.max_records:]
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
                    temp.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            os.replace(temp_name, self.path)
            temp_name = None
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass


def _sanitize_history_record(record: dict[str, object]) -> dict[str, object] | None:
    if record.get("record_type") == "cycle_memory":
        outcome = record.get("outcome")
        if outcome not in {"PASS", "FAIL", "BLOCKED"}:
            return None
        raw_paths = record.get("target_path", "")
        paths = raw_paths.split(",") if isinstance(raw_paths, str) else []
        safe_paths = [
            part.strip() for part in paths
            if part.strip()
            and _SAFE_RELATIVE_PATH.fullmatch(part.strip())
            and all(segment not in {".", ".."} for segment in part.strip().split("/"))
        ]
        improvements = record.get("improvements", [])
        count = len(improvements) if isinstance(improvements, (list, tuple)) else 0
        return {
            "record_type": "cycle_memory",
            "outcome": outcome,
            "cause": {
                "PASS": "development gate passed",
                "FAIL": "development gate failed",
                "BLOCKED": "development gate blocked",
            }[outcome],
            "improvements": ["improvement proposal recorded"] * min(count, 3),
            "next_action": "review outcome before execution",
            "target_path": ", ".join(safe_paths)[:_MAX_MEMORY_TEXT],
            "recurring_patterns": [],
        }

    kind = record.get("kind")
    if not isinstance(kind, str) or kind not in _SAFE_SIGNAL_DETAILS:
        return None
    task_id = record.get("task_id")
    if (
        not isinstance(task_id, str)
        or not _SAFE_TASK_ID.fullmatch(task_id)
        or _SENSITIVE_TASK_ID.fullmatch(task_id)
    ):
        task_id = None
    return {
        "kind": kind,
        "task_id": task_id,
        "detail": _SAFE_SIGNAL_DETAILS[kind],
    }


__all__ = ["SelfImprovementHistory", "SelfImprovementMemoryRecord"]
