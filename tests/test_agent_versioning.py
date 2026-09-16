import pytest
from core.agent_maintenance import AgentMaintenance, MaintenanceSeverity
from core.agent_versioning import AgentVersion, AgentVersionRegistry

def version(name="developer", number="1.0.0", status="active"):
    return AgentVersion(name, number, "2", "3", "1", "1", "2", status)

def test_tracks_current_and_rollback_target():
    registry = AgentVersionRegistry([version(number="1.0.0", status="candidate"), version(number="1.1.0")])
    assert registry.current("developer").version == "1.1.0"
    assert registry.rollback_target("developer").version == "1.0.0"

def test_rejects_duplicate_version():
    registry = AgentVersionRegistry([version()])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(version())

def test_validates_component_metadata():
    assert "prompt_version is required" in AgentVersion("developer", "1.0.0", prompt_version="").validate()

def test_maintenance_reports_missing_version():
    findings = AgentMaintenance().inspect_version("control_tower", None)
    assert findings[0].code == "VERSION_MISSING"
    assert findings[0].severity is MaintenanceSeverity.WARNING

def test_maintenance_has_no_finding_for_registered_version():
    assert AgentMaintenance().inspect_version("control_tower", version()) == ()
