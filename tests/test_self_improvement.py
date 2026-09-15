from __future__ import annotations

from core.agent_runtime import RuntimeReport
from core.self_improvement import SelfImprovementEngine, summarize_signals


def test_success_report_creates_success_signal() -> None:
    engine = SelfImprovementEngine()
    signals = engine.observe(RuntimeReport((), rounds=1, integration_ready=True))
    assert signals[0].kind == "success"
    assert engine.propose() is None


def test_failure_report_creates_debug_proposal() -> None:
    engine = SelfImprovementEngine()
    signals = engine.observe(RuntimeReport((), failed_task_id="test-1", error="pytest failed"))
    proposal = engine.propose()
    assert signals[0].kind == "failure"
    assert proposal is not None
    assert proposal.task is not None
    assert proposal.task.role.value == "debugger"
    assert proposal.task.task_id == "self-improvement:failure-analysis"


def test_repeated_repairs_create_review_signal() -> None:
    engine = SelfImprovementEngine()
    engine.observe(RuntimeReport((), repair_attempts=1))
    engine.observe(RuntimeReport((), repair_attempts=1))
    proposal = engine.propose()
    assert proposal is not None
    assert proposal.title == "Review recurring repair pattern"
    assert len(proposal.signals) == 2


def test_signal_buffer_is_bounded() -> None:
    engine = SelfImprovementEngine(max_signals=2)
    engine.observe(RuntimeReport((), repair_attempts=1))
    engine.observe(RuntimeReport((), repair_attempts=1))
    engine.observe(RuntimeReport((), repair_attempts=1))
    assert len(engine.signals) == 2


def test_summary_is_compact_and_deterministic() -> None:
    engine = SelfImprovementEngine()
    signals = engine.observe(RuntimeReport((), failed_task_id="t1", error="timeout"))
    assert summarize_signals(signals) == "failure:t1:timeout"
