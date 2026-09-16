import pytest

from core.agent_maintenance import AgentMaintenance, MaintenanceSeverity
from core.agent_versioning import AgentVersion, AgentVersionRegistry


def make_version(version: str, status: str = "active") -> AgentVersion:
    return AgentVersion(
        agent_name="developer",
        version=version,
        prompt_version="2",
        model_version="3",
        tool_version="1",
        memory_version="1",
        config_version="2",
        status=status,
    )


def test_version_registry_tracks_current_and_previous_version():
    registry = AgentVersionRegistry()
    registry.register(make_version("1.0.0", status="candidate"))
    registry.register(make_version("1.1.0", status="active"))

    assert registry.current("developer").version == "1.1.0"
    assert registry.rollback_target("developer").version == "1.0.0"


def test_version_registry_rejects_duplicate_version():
    registry = AgentVersionRegistry([make_version("1.0.0")])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(make_version("1.0.0"))


def test_version_validation_requires_component_metadata():
    version = AgentVersion(agent_name="developer", version="1.0.0", prompt_version="")
    assert "prompt_version is required" in version.validate()


def test_maintenance_is_read_only_and_reports_missing_version():
    findings = AgentMaintenance().inspect_version("control_tower", None)
    assert findings[0].code == "VERSION_MISSING"
    assert findings[0].severity is MaintenanceSeverity.WARNING


def test_maintenance_accepts_registered_version_without_findings():
    findings = AgentMaintenance().inspect_version("control_tower", make_version("1.0.0"))
    assert findings == ()
