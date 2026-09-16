import pytest

from core.agent_governance import AgentGovernance
from core.agent_specs import AgentLifecycle, AgentSpec
from core.agent_versioning import AgentVersion


class FakeAgent:
    name = "developer"
    description = "test agent"
    priority = 1
    enabled = True

    def can_handle(self, request):
        return True

    def handle(self, request):
        raise NotImplementedError


def spec(name="developer", lifecycle=AgentLifecycle.ENABLED):
    return AgentSpec.create(
        name=name,
        purpose="test",
        input_contract="request",
        output_contract="response",
        safety_constraints=("read-only test",),
        tests=("tests/test_agent_governance.py",),
        lifecycle=lifecycle,
    )


def version(name="developer", number="1.0.0"):
    return AgentVersion(name, number, lifecycle=AgentLifecycle.ENABLED)


def test_register_and_get_keeps_three_registries_consistent():
    governance = AgentGovernance()
    record = governance.register(FakeAgent(), spec(), version())
    assert record.name == "developer"
    current = governance.get("developer")
    assert current is not None
    assert current.agent is record.agent
    assert current.spec == record.spec
    assert current.version == record.version
    assert governance.names() == ("developer",)


def test_rejects_mismatched_component_names_before_mutation():
    governance = AgentGovernance()
    with pytest.raises(ValueError, match="names must match"):
        governance.register(FakeAgent(), spec("other"), version())
    assert governance.names() == ()


def test_rejects_non_enabled_runtime_registration_before_mutation():
    governance = AgentGovernance()
    reviewed = spec(lifecycle=AgentLifecycle.REVIEWED)
    with pytest.raises(ValueError, match="only enabled"):
        governance.register(FakeAgent(), reviewed, version())
    assert governance.names() == ()


def test_rejects_second_registration_without_partial_mutation():
    governance = AgentGovernance()
    governance.register(FakeAgent(), spec(), version())
    with pytest.raises(ValueError, match="already registered"):
        governance.register(FakeAgent(), spec(), version("developer", "2.0.0"))
    assert len(governance.names()) == 1
    assert len(governance.versions.history("developer")) == 1
