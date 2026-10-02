"""Latched, fail-closed emergency stop for autonomous development.

The controller has no reset operation by design. A stop latch is cleared only by
an external human/operator action that removes the latch file; the AI runtime
cannot release its own stop.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import tempfile


class StopReason(str, Enum):
    MANUAL_KILL = "manual-kill"
    PERMISSION_EXPANSION = "permission-expansion"
    SAFETY_GATE_BYPASS = "safety-gate-bypass"
    SECRET_ACCESS = "secret-access"
    SELF_DISABLE_STOP_CONTROL = "self-disable-stop-control"
    UNAUTHORIZED_EXTERNAL_ACTION = "unauthorized-external-action"
    SCOPE_EXPANSION = "scope-expansion"
    RESULT_MISMATCH = "result-mismatch"
    REPEATED_FAILURE = "repeated-failure"
    MUTUAL_AI_CONFLICT = "mutual-ai-conflict"


class ImmediateStop(RuntimeError):
    """Raised when autonomous execution is latched stopped."""


@dataclass(frozen=True)
class StopSignal:
    reason: StopReason
    evidence: str


_DANGEROUS_PATTERNS: tuple[tuple[StopReason, re.Pattern[str]], ...] = (
    (StopReason.SELF_DISABLE_STOP_CONTROL, re.compile(r"(disable|bypass|remove|delete).{0,60}(kill\s*switch|immediate\s*stop|safety\s*gate|stop\s*control)", re.I | re.S)),
    (StopReason.SAFETY_GATE_BYPASS, re.compile(r"(bypass|skip|disable).{0,40}(safety\s*gate|safety\s*check)", re.I | re.S)),
    (StopReason.PERMISSION_EXPANSION, re.compile(r"(grant|expand|escalat).{0,50}(permission|privilege|credential|admin|root)", re.I | re.S)),
    (StopReason.SECRET_ACCESS, re.compile(r"(steal|extract|dump|exfiltrat|obtain).{0,50}(secret|token|password|credential|api[_ -]?key)", re.I | re.S)),
    (StopReason.UNAUTHORIZED_EXTERNAL_ACTION, re.compile(r"(send|post|publish|delete|modify).{0,60}(external|production|third[- ]party).{0,60}(without|no|bypass).{0,30}(approval|authorization)", re.I | re.S)),
)


class ImmediateStopController:
    """Persistent stop latch. Missing/unreadable state is treated as stopped."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.environ.get("IMMEDIATE_STOP_PATH", "/tmp/line-bot-immediate-stop.json"))

    def _read(self) -> dict | None:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return data if isinstance(data, dict) and data.get("stopped") is True else {}

    def is_stopped(self) -> bool:
        """Return the latched stop state using one consistent state read.

        A missing latch means normal operation; an unreadable/corrupt latch
        fails closed and therefore blocks autonomous execution.
        """
        state = self._read()
        return state is None or bool(state)

    def assert_can_execute(self) -> None:
        if self.is_stopped():
            raise ImmediateStop(f"autonomous execution stopped: {self.path}")

    def request_stop(self, reason: StopReason, evidence: str) -> StopSignal:
        payload = {
            "stopped": True,
            "reason": reason.value,
            "evidence": evidence[-4000:],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return StopSignal(reason, evidence[-4000:])

    def inspect_text(self, text: str) -> StopSignal | None:
        if not text:
            return None
        for reason, pattern in _DANGEROUS_PATTERNS:
            if pattern.search(text):
                return self.request_stop(reason, text)
        return None


__all__ = ["ImmediateStop", "ImmediateStopController", "StopReason", "StopSignal"]
