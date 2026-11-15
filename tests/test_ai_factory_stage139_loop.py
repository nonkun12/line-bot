from dataclasses import dataclass
from core.ai_factory_orchestrator import (
    AgentCandidate, CandidateState, FactoryStage, LoopSafety, LoopTickReport, OrchestrationResult,
)
from core.ai_factory_stage139_loop import Stage139LoopController
from core.ai_factory_stage138_catalog import PendingAgentCatalog

@dataclass
class FakeOrchestrator:
    report: object
    calls: int = 0
    def run_tick(self, tick_id, gaps, *, safety):
        self.calls += 1
        return self.report

def candidate(name="new-agent"):
    return AgentCandidate("gap-1:abc123", "gap-1", "audit", name, "a" * 64,
        ("test evidence",), ("review evidence",), CandidateState.AWAITING_APPROVAL)

def test_safety_holds_stop_before_orchestrator_call():
    fake = FakeOrchestrator(LoopTickReport("t", ()))
    controller = Stage139LoopController(orchestrator=fake, catalog=PendingAgentCatalog(),
        candidate_lookup=lambda name: None)
    report = controller.run_tick("t", (), safety=LoopSafety(hold_active=True))
    assert fake.calls == 0
    assert report.tick.stopped_reason == "HOLD is active"

def test_tick_caps_candidates_at_four_and_files_pending_metadata():
    results = tuple(OrchestrationResult(f"gap-{i}", FactoryStage.CATALOG, candidate=candidate(f"agent-{i}"))
        for i in range(4))
    fake = FakeOrchestrator(LoopTickReport("tick-1", results))
    record = object()  # Catalog stub below accepts a duck-typed reviewed record
    class Catalog:
        def __init__(self): self.items=[]
        def submit(self, value):
            self.items.append(value)
            return value
    catalog = Catalog()
    controller = Stage139LoopController(orchestrator=fake, catalog=catalog, candidate_lookup=lambda name: record)
    report = controller.run_tick("tick-1", (), safety=LoopSafety(max_candidates_per_tick=4))
    assert len(report.pending_candidates) == 4
    assert len(catalog.items) == 4

def test_catalog_failure_converts_success_to_blocked_result():
    fake = FakeOrchestrator(LoopTickReport("t", (OrchestrationResult("gap-1", FactoryStage.CATALOG,
        candidate=candidate()),)))
    class Catalog:
        def submit(self, record): raise PermissionError("review evidence missing")
    controller = Stage139LoopController(orchestrator=fake, catalog=Catalog(),
        candidate_lookup=lambda name: object())
    report = controller.run_tick("t", ())
    assert report.tick.processed[0].candidate is None
    assert "catalog rejected" in report.tick.processed[0].blocked_reason

def test_missing_record_blocks_catalog_submission():
    fake = FakeOrchestrator(LoopTickReport("t", (OrchestrationResult("gap-1", FactoryStage.CATALOG,
        candidate=candidate()),)))
    controller = Stage139LoopController(orchestrator=fake, catalog=PendingAgentCatalog(),
        candidate_lookup=lambda name: None)
    report = controller.run_tick("t", ())
    assert report.catalog_failures
    assert report.tick.blocked == 1

def test_kill_switch_and_budget_are_fail_closed():
    fake = FakeOrchestrator(LoopTickReport("t", ()))
    controller = Stage139LoopController(orchestrator=fake, catalog=PendingAgentCatalog(),
        candidate_lookup=lambda name: None)
    assert controller.run_tick("t", (), safety=LoopSafety(kill_switch_active=True)).tick.stopped_reason
    assert controller.run_tick("t", (), safety=LoopSafety(budget_available=False)).tick.stopped_reason
    assert fake.calls == 0
