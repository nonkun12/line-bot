"""Bounded durable history for self-improvement signals and cycle memory.

The store is provider-neutral and append-only. Persisted free text is never
trusted: legacy v1 rows are normalized to allowlisted categories on read.
Corrupt or unknown rows fail closed before any append can rewrite the file.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

from .self_improvement import ImprovementSignal

_DEFAULT_MAX_RECORDS = 200
_MAX_MAX_RECORDS = 200
_MAX_MEMORY_TEXT = 1200
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SAFE_DETAILS = {
    "success": {"task passed or verified no-change"},
    "repair": {"development required repair attempts"},
    "failure": {
        "development failure observed",
        "development failure observed: pytest",
        "development failure observed: timeout",
        "development failure observed: import",
        "development failure observed: assertion",
        "development failure observed: blocked",
        "development failure observed: runtime",
    },
}
_MEMORY_CAUSES = {
    "PASS": "development gate passed",
    "FAIL": "development cycle failed",
    "BLOCKED": "development cycle blocked",
}
_MEMORY_IMPROVEMENTS = {
    "retain verified outcome for next cycle",
    "review recurring development failure",
    "resolve safety or evidence block before retry",
}
_MEMORY_NEXT_ACTIONS = {
    "continue bounded development loop after review",
    "review failure evidence before another attempt",
    "require evidence and safety review before resume",
}
_SAFE_PATTERN_CODES = set().union(*_SAFE_DETAILS.values())


def _safe_task_id(value: object) -> str | None:
    return value if isinstance(value, str) and _TASK_ID.fullmatch(value) else None


def _legacy_detail(kind: str) -> str:
    return {
        "success": "task passed or verified no-change",
        "repair": "development required repair attempts",
        "failure": "development failure observed",
    }[kind]


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
        if self.outcome not in _MEMORY_CAUSES:
            raise ValueError("invalid memory outcome")
        if self.cause != _MEMORY_CAUSES[self.outcome]:
            raise ValueError("memory cause must use an allowlisted outcome code")
        if self.target_path:
            raise ValueError("memory target_path must be empty")
        if self.next_action not in _MEMORY_NEXT_ACTIONS:
            raise ValueError("memory next_action is not allowlisted")
        if len(self.improvements) > 3 or len(self.recurring_patterns) > 5:
            raise ValueError("memory list exceeds bounded length")
        if any(value not in _MEMORY_IMPROVEMENTS for value in self.improvements):
            raise ValueError("memory improvement is not allowlisted")
        if any(value not in _SAFE_PATTERN_CODES for value in self.recurring_patterns):
            raise ValueError("memory recurring pattern is not allowlisted")


class SelfImprovementHistory:
    """Persist a bounded signal history with strict, loss-preventing reads."""

    def __init__(self, path: str | Path, *, max_records: int = _DEFAULT_MAX_RECORDS) -> None:
        if max_records < 1 or max_records > _MAX_MAX_RECORDS:
            raise ValueError("max_records must be between 1 and 200")
        self.path = Path(path)
        self.max_records = max_records

    def append(self, signals: Iterable[ImprovementSignal]) -> None:
        records = self._read_records()
        for signal in signals:
            if not isinstance(signal, ImprovementSignal):
                raise TypeError("history entries must be ImprovementSignal")
            records.append(asdict(signal))
        self._atomic_write(records)

    def append_memory(self, memory: SelfImprovementMemoryRecord) -> None:
        if not isinstance(memory, SelfImprovementMemoryRecord):
            raise TypeError("memory must be SelfImprovementMemoryRecord")
        records = self._read_records()
        records.append({"record_type": "cycle_memory", **asdict(memory)})
        self._atomic_write(records)

    def load(self) -> tuple[ImprovementSignal, ...]:
        result: list[ImprovementSignal] = []
        for record in self._read_records():
            if record.get("record_type") == "cycle_memory":
                continue
            result.append(ImprovementSignal(
                kind=str(record["kind"]),
                task_id=record.get("task_id"),
                detail=str(record["detail"]),
            ))
        return tuple(result)

    def load_memory(self, *, limit: int = 5) -> tuple[SelfImprovementMemoryRecord, ...]:
        if limit < 1 or limit > 20:
            raise ValueError("limit must be between 1 and 20")
        result: list[SelfImprovementMemoryRecord] = []
        for record in self._read_records():
            if record.get("record_type") != "cycle_memory":
                continue
            result.append(SelfImprovementMemoryRecord(
                outcome=str(record["outcome"]),
                cause=str(record["cause"]),
                improvements=tuple(record["improvements"]),
                next_action=str(record["next_action"]),
                target_path=str(record["target_path"]),
                recurring_patterns=tuple(record["recurring_patterns"]),
            ))
        return tuple(result[-limit:])

    def _read_records(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        # Scan every line, not only the retained tail: old corruption must not
        # be silently discarded by a later bounded rewrite.
        lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[dict[str, object]] = []
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"history JSONL is corrupt at line {line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"history row is invalid at line {line_number}")
            records.append(self._normalize_record(value, line_number))
        return records[-self.max_records:]

    @staticmethod
    def _normalize_record(row: dict[str, object], line_number: int) -> dict[str, object]:
        if row.get("record_type") == "cycle_memory":
            required = {"record_type", "outcome", "cause", "improvements", "next_action", "target_path", "recurring_patterns"}
            if set(row) not in (required, required | {"cycle_id"}):
                raise ValueError(f"cycle memory schema is invalid at line {line_number}")
            outcome = row.get("outcome")
            cycle_id = row.get("cycle_id")
            if "cycle_id" in row and (
                not isinstance(cycle_id, str) or not re.fullmatch(r"[0-9]{1,20}", cycle_id)
            ):
                raise ValueError(f"cycle memory ID is invalid at line {line_number}")
            if not isinstance(outcome, str) or outcome not in _MEMORY_CAUSES:
                raise ValueError(f"cycle memory outcome is invalid at line {line_number}")
            # v1 memory could contain exception text and arbitrary paths. Keep
            # only the verified outcome; do not infer a more specific cause.
            if (
                row.get("cause") != _MEMORY_CAUSES[outcome]
                or row.get("target_path") != ""
                or not isinstance(row.get("next_action"), str)
                or row.get("next_action") not in _MEMORY_NEXT_ACTIONS
                or not isinstance(row.get("improvements"), list)
                or any(not isinstance(item, str) or item not in _MEMORY_IMPROVEMENTS for item in row["improvements"])
                or not isinstance(row.get("recurring_patterns"), list)
                or any(not isinstance(item, str) or item not in _SAFE_PATTERN_CODES for item in row["recurring_patterns"])
            ):
                return {
                    "record_type": "cycle_memory",
                    "outcome": outcome,
                    "cause": _MEMORY_CAUSES[outcome],
                    "improvements": [],
                    "next_action": (
                        "continue bounded development loop after review" if outcome == "PASS"
                        else "require evidence and safety review before resume" if outcome == "BLOCKED"
                        else "review failure evidence before another attempt"
                    ),
                    "target_path": "",
                    "recurring_patterns": [],
                }
            normalized = dict(row)
            normalized["cause"] = _MEMORY_CAUSES[outcome]
            normalized["improvements"] = list(row["improvements"]) if isinstance(row.get("improvements"), list) and all(isinstance(item, str) and item in _MEMORY_IMPROVEMENTS for item in row["improvements"]) else []
            normalized["next_action"] = row["next_action"] if isinstance(row.get("next_action"), str) and row.get("next_action") in _MEMORY_NEXT_ACTIONS else (
                "continue bounded development loop after review" if outcome == "PASS"
                else "require evidence and safety review before resume" if outcome == "BLOCKED"
                else "review failure evidence before another attempt"
            )
            normalized["target_path"] = ""
            normalized["recurring_patterns"] = list(row["recurring_patterns"]) if isinstance(row.get("recurring_patterns"), list) and all(isinstance(item, str) and item in _SAFE_PATTERN_CODES for item in row["recurring_patterns"]) else []
            return normalized

        if set(row) != {"kind", "task_id", "detail"}:
            raise ValueError(f"self-improvement signal schema is invalid at line {line_number}")
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in _SAFE_DETAILS:
            raise ValueError(f"self-improvement signal kind is invalid at line {line_number}")
        detail = row.get("detail")
        # Existing v1 free-text details are deliberately downgraded to a
        # generic category. Only new, exact allowlisted codes retain detail.
        safe_detail = detail if isinstance(detail, str) and detail in _SAFE_DETAILS[kind] else _legacy_detail(kind)
        return {"kind": kind, "task_id": _safe_task_id(row.get("task_id")), "detail": safe_detail}

    def _atomic_write(self, records: list[dict[str, object]]) -> None:
        records = records[-self.max_records:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", delete=False,
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


__all__ = ["SelfImprovementHistory", "SelfImprovementMemoryRecord"]
