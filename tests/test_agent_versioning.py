import pytest

from core.agent_maintenance import AgentMaintenance, MaintenanceSeverity
from core.agent_specs import AgentLifecycle
from core.agent_versioning import AgentVersion, AgentVersionRegistry


def version(name="developer", number="1.0.0", lifecycle=AgentLifecycle.ENABLED):
    return AgentVersion(name, number, "2", "3", "1", "1", "2", lifecycle)


def test_tracks_current_and_rollback_target():
    registry = AgentVersionRegistry(
        [version(number="1.0.0", lifecycle=AgentLifecycle.REVIEWED), version(number="1.1.0")]
    )
    assert registry.current("developer").version == "1.1.0"
    assert registry.rollback_target("developer").version == "1.0.0"


def test_rejects_duplicate_version():
    registry = AgentVersionRegistry([version()])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(version())


def test_rejects_multiple_enabled_versions():
    registry = AgentVersionRegistry([version()])
    with pytest.raises(ValueError, match="active version already registered"):
        registry.register(version(number="2.0.0"))


def test_validates_component_metadata():
    assert "prompt_version is required" in AgentVersion("developer", "1.0.0", prompt_version="").validate()


def test_maintenance_reports_missing_version():
    findings = AgentMaintenance().inspect_version("control_tower", None)
    assert findings[0].code == "VERSION_MISSING"
    assert findings[0].severity is MaintenanceSeverity.WARNING


def test_maintenance_rejects_wrong_component_version():
    findings = AgentMaintenance().inspect_version("control_tower", version())
    assert findings[0].code == "VERSION_COMPONENT_MISMATCH"
    assert findings[0].severity is MaintenanceSeverity.ERROR


def test_maintenance_has_no_finding_for_registered_version():
    assert AgentMaintenance().inspect_version("control_tower", version(name="control_tower")) == ()
