import pytest

from core.agent_architecture import SPECIALIST_MODULES
from core.agent_factory import AgentFactory, AgentBuild, AgentReviewReport, AgentTestReport, GeneratedFile
from core.agent_specs import AgentLifecycle, AgentSpec
from core.capability_gap_discovery import (
    AgentCapabilityInventory,
    CapabilityGapArchitect,
    CapabilityGapPlanner,
    CapabilityRecord,
    CapabilityRequirement,
)
from core.specialist_registry import SpecialistRegistration, SpecialistRegistry
from core.management_contract import Specialist


class Designer:
    def __init__(self):
        self.seen = []

    def design(self, gap):
        self.seen.append(gap)
        key = gap.capability.replace("-", "_")
        return AgentSpec.create(
            name=f"{key}_specialist",
            purpose=gap.requirement.description,
            input_contract=gap.requirement.input_contract,
            output_contract=gap.requirement.output_contract,
            safety_constraints=gap.requirement.safety_constraints,
            tests=gap.requirement.validation_tests or ("tests/agents/generated/test_capability.py",),
        )


class Builder:
    def build(self, spec):
        return AgentBuild(spec, (
            GeneratedFile("agents/generated/capability.py", "class CapabilityAgent: pass"),
            GeneratedFile("tests/agents/generated/test_capability.py", "def test_contract(): assert True"),
        ))


class Sandbox:
    def test(self, build):
        return AgentTestReport(True, ("sandbox: passed",))


class Reviewer:
    def review(self, build, tests):
        return AgentReviewReport(True, ("scope reviewed",))


def test_platform_inventory_distinguishes_declared_from_enabled():
    inventory = AgentCapabilityInventory.from_platform()
    assert any(x.key == "conversation" and x.state == "declared" for x in inventory.records)
    assert inventory.providers("conversation") == ()
    assert len(SPECIALIST_MODULES) == 23


def test_only_enabled_registry_capabilities_cover_a_requirement():
    registry = SpecialistRegistry((
        SpecialistRegistration(Specialist.NEWS, lambda: None, ("news_retrieval", "fact_check")),
    ))
    inventory = AgentCapabilityInventory.from_platform(specialist_registry=registry)
    report = CapabilityGapPlanner().analyze((
        CapabilityRequirement("news_retrieval", "retrieve news"),
        CapabilityRequirement("fact_check", "verify factual claims"),
        CapabilityRequirement("long_context_synthesis", "synthesize long documents"),
    ), inventory)
    assert report.covered == ("news_retrieval", "fact_check")
    assert [gap.capability for gap in report.gaps] == ["long_context_synthesis"]


def test_declared_but_not_enabled_capability_is_reported_as_gap_with_evidence():
    inventory = AgentCapabilityInventory.from_platform()
    report = CapabilityGapPlanner().analyze((
        CapabilityRequirement("conversation", "handle conversation"),
    ), inventory)
    assert len(report.gaps) == 1
    assert report.gaps[0].declared_matches
    assert "no enabled handler" in report.gaps[0].evidence[0]


def test_unknown_capability_is_reported_without_inventing_provider():
    inventory = AgentCapabilityInventory()
    report = CapabilityGapPlanner().analyze((
        CapabilityRequirement("quantum_planning", "plan quantum experiments"),
    ), inventory)
    assert report.gaps[0].declared_matches == ()
    assert "no matching enabled capability" in report.gaps[0].evidence[0]


def test_duplicate_requirements_fail_closed():
    planner = CapabilityGapPlanner()
    requirement = CapabilityRequirement("research", "research")
    with pytest.raises(ValueError, match="duplicate"):
        planner.analyze((requirement, requirement), AgentCapabilityInventory())


def test_architect_adapter_binds_gap_and_stamps_evidence_metadata():
    report = CapabilityGapPlanner().analyze((
        CapabilityRequirement("risk_analysis", "analyze operational risks"),
    ), AgentCapabilityInventory())
    designer = Designer()
    architect = CapabilityGapArchitect(designer)
    gap = report.gaps[0]
    gap_id = architect.bind(gap)
    spec = architect.design(gap_id)
    assert spec.lifecycle == AgentLifecycle.GENERATED
    assert spec.metadata["capability_gap_id"] == gap.gap_id
    assert spec.metadata["capability"] == "risk_analysis"
    assert designer.seen == [gap]


def test_architect_rejects_unbound_gap_id():
    architect = CapabilityGapArchitect(Designer())
    with pytest.raises(KeyError, match="unknown capability gap"):
        architect.design("capability-gap-not-bound")


def test_architect_rejects_non_generated_spec():
    class BadDesigner:
        def design(self, gap):
            return AgentSpec.create(
                name="unsafe_specialist",
                purpose="bad",
                input_contract="input",
                output_contract="output",
                safety_constraints=("read-only",),
                tests=("test",),
                lifecycle=AgentLifecycle.ENABLED,
            )
    report = CapabilityGapPlanner().analyze((
        CapabilityRequirement("unsafe", "unsafe capability"),
    ), AgentCapabilityInventory())
    architect = CapabilityGapArchitect(BadDesigner())
    with pytest.raises(ValueError, match="GENERATED"):
        architect.design(architect.bind(report.gaps[0]))


def test_discovered_gap_flows_into_stage_121_factory():
    report = CapabilityGapPlanner().analyze((
        CapabilityRequirement("research", "perform bounded research"),
    ), AgentCapabilityInventory())
    architect = CapabilityGapArchitect(Designer())
    gap_id = architect.bind(report.gaps[0])
    factory = AgentFactory(
        architect=architect,
        builder=Builder(),
        sandbox=Sandbox(),
        reviewer=Reviewer(),
    )
    record = factory.create_candidate(gap_id)
    assert record.lifecycle == AgentLifecycle.REVIEWED
    assert record.build.spec.metadata["capability_gap_id"] == gap_id
    assert factory.governance.names() == ()


def test_inventory_custom_records_are_not_mutated_by_planner():
    inventory = AgentCapabilityInventory((
        CapabilityRecord("existing", "test", "enabled"),
    ))
    before = inventory.records
    CapabilityGapPlanner().analyze((
        CapabilityRequirement("new_capability", "new capability"),
    ), inventory)
    assert inventory.records == before
