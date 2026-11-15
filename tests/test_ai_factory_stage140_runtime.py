from core.agent_collaboration_pipeline import CollaborationRoles
from core.ai_factory_orchestrator import LoopSafety
from core.ai_factory_stage132_local_models import LocalModelConfig
from core.ai_factory_stage137_runtime import Stage137Config
from core.ai_factory_stage140_runtime import Stage140Config, build_stage140_runtime
from core.capability_gap_discovery import (
    AgentCapabilityInventory, CapabilityRecord, CapabilityRequirement,
)

class FakeClient:
    def __init__(self, config): self.config = config
    def chat(self, *, system, prompt): raise AssertionError("models must not run in these tests")

def runtime():
    models = Stage137Config(
        LocalModelConfig("designer"), LocalModelConfig("architect"),
        LocalModelConfig("builder"), LocalModelConfig("reviewer"),
        "python:3.13-slim@sha256:" + "b" * 64,
    )
    return build_stage140_runtime(
        config=Stage140Config(models),
        roles=CollaborationRoles("architect-agent", "builder-agent", "tester-agent", "reviewer-agent"),
        test_gate=lambda *a: None, review_gate=lambda *a: None,
        sandbox_runner=lambda *a, **k: None, model_client_factory=FakeClient,
    )

def test_stage140_finds_uncovered_capability_and_reports_gap_without_running_when_held():
    app = runtime()
    requirement = CapabilityRequirement("video-analysis", "Analyze video evidence", validation_tests=("test-frame",))
    inventory = AgentCapabilityInventory((CapabilityRecord("video-analysis", "architecture", "declared"),))
    report = app.run_cycle("tick-140", (requirement,), inventory, safety=LoopSafety(hold_active=True))
    assert len(report.discovery.gaps) == 1
    assert report.loop.tick.stopped_reason == "HOLD is active"
    assert app.catalog.count() == 0

def test_stage140_does_not_create_agent_when_capability_is_already_enabled():
    app = runtime()
    requirement = CapabilityRequirement("audit", "Audit repository", validation_tests=("test-audit",))
    inventory = AgentCapabilityInventory((CapabilityRecord("audit", "specialist_registry", "enabled"),))
    report = app.run_cycle("tick-140", (requirement,), inventory)
    assert report.discovery.gaps == ()
    assert report.discovery.covered == ("audit",)
    assert report.loop.tick.stopped_reason == "no capability gaps detected"
    assert app.catalog.count() == 0

def test_stage140_fails_closed_on_kill_switch_before_gap_binding():
    app = runtime()
    requirement = CapabilityRequirement("missing", "Missing capability", validation_tests=("test",))
    inventory = AgentCapabilityInventory()
    report = app.run_cycle("tick-140", (requirement,), inventory, safety=LoopSafety(kill_switch_active=True))
    assert report.loop.tick.stopped_reason == "global kill switch is active"
    assert app.catalog.count() == 0

def test_stage140_exposes_only_pending_catalog_and_no_auto_enable():
    app = runtime()
    assert app.catalog.count() == 0
    assert app.pipeline.pipeline.factory.factory_adapter.factory.approval_gate is None
    assert app.pipeline.pipeline.factory.factory_adapter.factory.permitted_tools == frozenset()
    assert app.pipeline.pipeline.factory.factory_adapter.factory.permitted_resource_scopes == frozenset()
