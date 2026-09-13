"""Bounded TEST -> DEBUG -> REFACTOR -> TEST quality gate."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol


class QualityRole(str, Enum):
    TEST = "test"
    DEBUG = "debug"
    REFACTOR = "refactor"


@dataclass(frozen=True)
class QualityResult:
    role: QualityRole
    success: bool
    summary: str = ""


class QualityAgent(Protocol):
    def run(self, context: Mapping[str, object]) -> QualityResult:
        ...


def run_quality_pipeline(
    agents: Mapping[QualityRole, QualityAgent],
    context: Mapping[str, object],
) -> tuple[QualityResult, ...]:
    """Run quality gates conservatively; never refactor passing code."""
    for role in (QualityRole.TEST, QualityRole.DEBUG, QualityRole.REFACTOR):
        if role not in agents:
            raise ValueError(f"missing quality agent: {role.value}")

    results: list[QualityResult] = []
    first_test = agents[QualityRole.TEST].run(dict(context))
    results.append(first_test)
    if first_test.success:
        return tuple(results)

    debug = agents[QualityRole.DEBUG].run({**context, "failed_test": first_test})
    results.append(debug)
    if not debug.success:
        return tuple(results)

    refactor = agents[QualityRole.REFACTOR].run({**context, "debug_result": debug})
    results.append(refactor)
    if not refactor.success:
        return tuple(results)

    final_test = agents[QualityRole.TEST].run({**context, "refactor_result": refactor})
    results.append(final_test)
    return tuple(results)
