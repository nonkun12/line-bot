"""Bounded outer loop controller for Management AI + distributed specialists.

This layer makes loop-engineering explicit without creating a second execution
path. ManagementAI remains responsible for planning, SpecialistGate checks,
bounded dispatch, and result collection. The controller adds loop identity,
bounded iteration, feedback lineage, and explicit stop reasons.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import uuid4

from .management_ai import ManagementAI, ManagementRun
from .management_contract import ManagementRequest


_MAX_LOOP_ID_CHARS = 64
_MAX_FEEDBACK_ITEMS = 6
_MAX_FEEDBACK_ITEM_CHARS = 1800


@dataclass(frozen=True)
class LoopObservation:
    """Immutable evidence projected from one management round."""

    loop_id: str
    round_number: int
    task_id: str
    success: bool
    role: str
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.loop_id, str) or not self.loop_id.strip():
            raise ValueError("loop_id is required")
        if len(self.loop_id) > _MAX_LOOP_ID_CHARS:
            raise ValueError("loop_id exceeds 64 characters")
        if (
            not isinstance(self.round_number, int)
            or isinstance(self.round_number, bool)
            or self.round_number < 1
        ):
            raise ValueError("round_number must be a positive integer")
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id is required")
        if not isinstance(self.role, str) or not self.role.strip():
            raise ValueError("role is required")
        if not isinstance(self.success, bool):
            raise ValueError("success must be a bool")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("summary is required")
        if len(self.summary) > _MAX_FEEDBACK_ITEM_CHARS:
            raise ValueError("summary exceeds 1800 characters")


@dataclass(frozen=True)
class LoopIteration:
    """One management round with loop identity and bounded observations."""

    loop_id: str
    round_number: int
    management_run: ManagementRun
    observations: tuple[LoopObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.management_run, ManagementRun):
            raise TypeError("management_run must be a ManagementRun")
        if len(self.observations) > 6:
            raise ValueError("too many loop observations")
        if any(item.loop_id != self.loop_id for item in self.observations):
            raise ValueError("loop observation lineage mismatch")
        if any(item.round_number != self.round_number for item in self.observations):
            raise ValueError("loop observation round mismatch")


@dataclass(frozen=True)
class LoopRun:
    """Complete bounded outer loop execution."""

    loop_id: str
    iterations: tuple[LoopIteration, ...]
    stopped_reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.loop_id, str) or not self.loop_id.strip():
            raise ValueError("loop_id is required")
        if len(self.loop_id) > _MAX_LOOP_ID_CHARS:
            raise ValueError("loop_id exceeds 64 characters")
        if not self.iterations:
            raise ValueError("loop must contain at least one iteration")
        if len(self.iterations) > 3:
            raise ValueError("loop cannot contain more than 3 iterations")
        if any(item.loop_id != self.loop_id for item in self.iterations):
            raise ValueError("loop iteration lineage mismatch")
        if tuple(item.round_number for item in self.iterations) != tuple(range(1, len(self.iterations) + 1)):
            raise ValueError("loop iterations must be sequential")
        if not isinstance(self.stopped_reason, str) or not self.stopped_reason.strip():
            raise ValueError("stopped_reason is required")

    @property
    def success(self) -> bool:
        return all(iteration.management_run.success for iteration in self.iterations)


class LoopController:
    """Run the bounded ManagementAI feedback loop with explicit lineage."""

    def __init__(self, management_ai: ManagementAI, *, max_rounds: int = 3) -> None:
        if not isinstance(management_ai, ManagementAI):
            raise TypeError("management_ai must be a ManagementAI")
        if max_rounds < 1 or max_rounds > 3:
            raise ValueError("max_rounds must be between 1 and 3")
        self._management_ai = management_ai
        self._max_rounds = max_rounds

    def run(self, request: ManagementRequest, *, loop_id: str | None = None) -> LoopRun:
        """Execute bounded rounds and feed verified observations forward.

        The controller never changes specialist permissions. It delegates every
        round to ManagementAI, so existing capability and execution gates remain
        the only specialist dispatch path.
        """
        if not isinstance(request, ManagementRequest):
            raise TypeError("request must be a ManagementRequest")
        identity = (loop_id or uuid4().hex).strip()
        if not identity:
            raise ValueError("loop_id is required")
        if len(identity) > _MAX_LOOP_ID_CHARS:
            raise ValueError("loop_id exceeds 64 characters")

        iterations: list[LoopIteration] = []
        feedback: tuple[str, ...] = ()

        for round_number in range(1, self._max_rounds + 1):
            scoped_request = _with_loop_id(request, identity)
            management_run = self._management_ai.run(scoped_request, feedback)
            observations = tuple(
                LoopObservation(
                    loop_id=identity,
                    round_number=round_number,
                    task_id=item.task_id,
                    success=item.success,
                    role=item.role.value,
                    summary=item.summary,
                )
                for item in management_run.observations
            )
            iterations.append(
                LoopIteration(
                    loop_id=identity,
                    round_number=round_number,
                    management_run=management_run,
                    observations=observations,
                )
            )

            if not management_run.success:
                return LoopRun(identity, tuple(iterations), "round failed; fail closed")
            if not management_run.plan.continue_after_round:
                return LoopRun(identity, tuple(iterations), "manager stopped the cycle")
            if round_number == self._max_rounds:
                return LoopRun(identity, tuple(iterations), "bounded round limit reached")

            feedback = _feedback_from_observations(observations)

        return LoopRun(identity, tuple(iterations), "bounded round limit reached")


def _with_loop_id(request: ManagementRequest, loop_id: str) -> ManagementRequest:
    metadata = dict(request.metadata)
    existing = metadata.get("loop_id")
    if existing is not None and str(existing) != loop_id:
        raise ValueError("request loop_id conflicts with controller loop_id")
    metadata["loop_id"] = loop_id
    return ManagementRequest(
        user_id=request.user_id,
        message=request.message,
        channel=request.channel,
        metadata=metadata,
    )


def _feedback_from_observations(observations: Sequence[LoopObservation]) -> tuple[str, ...]:
    return tuple(
        (
            f"OBSERVATION loop_id={item.loop_id}; round={item.round_number}; "
            f"task_id={item.task_id}; role={item.role}; success={item.success}; "
            f"summary={item.summary}"
        )[:_MAX_FEEDBACK_ITEM_CHARS]
        for item in observations[-_MAX_FEEDBACK_ITEMS:]
    )


__all__ = ["LoopController", "LoopIteration", "LoopObservation", "LoopRun"]
