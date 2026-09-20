"""Durable, fail-closed storage for approved self-improvement handoffs.

Persisted records are treated as untrusted input. Loading re-checks the shared
self-improvement policy, DEBUGGER-only role restriction, and exact task hash.
This module never executes a handoff or grants permissions.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .control_tower import task_hash
from .multi_agent import AgentRole, AgentTask
from .self_improvement_handoff import ApprovedImprovementHandoff
from .self_improvement_policy import SelfImprovementDecision, assess_self_improvement

_SCHEMA_VERSION = 1
_DEFAULT_MAX_RECORDS = 50
_MAX_MAX_RECORDS = 200


class ApprovedImprovementHandoffStore:
    """Persist a bounded queue of immutable, validated handoffs."""

    def __init__(self, path: str | Path, *, max_records: int = _DEFAULT_MAX_RECORDS) -> None:
        if max_records < 1 or max_records > _MAX_MAX_RECORDS:
            raise ValueError("max_records must be between 1 and 200")
        self.path = Path(path)
        self.max_records = max_records

    def append(self, handoff: ApprovedImprovementHandoff) -> None:
        """Persist one already-approved handoff after re-validating its boundary."""
        self._validate_handoff(handoff)
        records = self._read_records()
        encoded = self._encode(handoff)
        if not any(record.get("task_hash") == encoded["task_hash"] for record in records):
            records.append(encoded)
        self._atomic_write(records[-self.max_records :])

    def load(self) -> tuple[ApprovedImprovementHandoff, ...]:
        """Load only records that still satisfy all safety and integrity checks."""
        result: list[ApprovedImprovementHandoff] = []
        for record in self._read_records():
            try:
                handoff = self._decode(record)
                self._validate_handoff(handoff)
            except (KeyError, TypeError, ValueError, PermissionError):
                continue
            result.append(handoff)
        return tuple(result[-self.max_records :])

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

    @staticmethod
    def _encode(handoff: ApprovedImprovementHandoff) -> dict[str, object]:
        task = handoff.task
        return {
            "schema_version": _SCHEMA_VERSION,
            "task_id": task.task_id,
            "role": task.role.value,
            "instruction": task.instruction,
            "resources": sorted(task.resources),
            "depends_on": list(task.depends_on),
            "priority": task.priority,
            "task_hash": handoff.task_hash,
            "allowed_paths": list(handoff.allowed_paths),
        }

    @staticmethod
    def _decode(record: dict[str, object]) -> ApprovedImprovementHandoff:
        if record.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported handoff schema")
        role = AgentRole(str(record["role"]))
        task = AgentTask(
            task_id=str(record["task_id"]),
            role=role,
            instruction=str(record["instruction"]),
            resources=frozenset(str(value) for value in record.get("resources", [])),
            depends_on=tuple(str(value) for value in record.get("depends_on", [])),
            priority=int(record.get("priority", 0)),
        )
        raw_paths = record["allowed_paths"]
        if not isinstance(raw_paths, list) or not raw_paths:
            raise ValueError("allowed_paths are required")
        paths = tuple(str(path).strip() for path in raw_paths)
        if any(not path for path in paths) or len(set(paths)) != len(paths):
            raise ValueError("allowed_paths are malformed")
        return ApprovedImprovementHandoff(
            task=task,
            task_hash=str(record["task_hash"]),
            allowed_paths=tuple(sorted(paths)),
        )

    @staticmethod
    def _validate_handoff(handoff: ApprovedImprovementHandoff) -> None:
        if not isinstance(handoff, ApprovedImprovementHandoff):
            raise TypeError("handoff must be an ApprovedImprovementHandoff")
        if handoff.task.role is not AgentRole.DEBUGGER:
            raise PermissionError("only bounded debugger tasks may be persisted")
        paths = tuple(handoff.allowed_paths)
        if not paths or len(set(paths)) != len(paths):
            raise ValueError("allowed_paths are malformed")
        assessment = assess_self_improvement(paths)
        if assessment.decision is not SelfImprovementDecision.AUTONOMOUS_REVIEW:
            raise PermissionError("persisted handoff target policy is not autonomous")
        expected_hash = task_hash(handoff.task)
        if expected_hash is None or handoff.task_hash != expected_hash:
            raise ValueError("persisted handoff task hash mismatch")

    def _atomic_write(self, records: list[dict[str, object]]) -> None:
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
                    temp.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            os.replace(temp_name, self.path)
            temp_name = None
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass


__all__ = ["ApprovedImprovementHandoffStore"]
