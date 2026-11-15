import pytest
from dataclasses import replace
from core.agent_factory import AgentBuild, AgentCreationRecord, AgentReviewReport, AgentTestReport, GeneratedFile
from core.agent_specs import AgentLifecycle, AgentSpec
from core.ai_factory_stage138_catalog import CandidateStatus, PendingAgentCatalog

def record(name="catalog-auditor", tools=(), scopes=(), lifecycle=AgentLifecycle.REVIEWED, passed=True, approved=True):
    spec = AgentSpec.create(name=name, purpose="Audit", input_contract="diff", output_contract="findings",
        allowed_tools=tools, resource_scope=scopes, safety_constraints=("read only",), tests=("test_contract",),
        lifecycle=lifecycle)
    build = AgentBuild(spec, (GeneratedFile("agents/generated/a.py", "class A: pass"),
        GeneratedFile("tests/agents/generated/test_a.py", "def test_a(): assert True")))
    return AgentCreationRecord(build, AgentTestReport(passed, ("sandbox passed",) if passed else (), ()),
        AgentReviewReport(approved, ("reviewed",), () if approved else ("blocked",)), lifecycle)

def test_catalog_stores_metadata_only_pending_candidate():
    catalog = PendingAgentCatalog()
    candidate = catalog.submit(record())
    assert candidate.status is CandidateStatus.PENDING_HUMAN_APPROVAL
    assert candidate.enabled is False
    assert candidate.artifact_digest and candidate.spec_digest
    assert candidate.artifact_paths
    assert not hasattr(candidate, "artifact_contents")
    assert catalog.count() == 1

def test_catalog_is_idempotent_for_same_candidate():
    catalog = PendingAgentCatalog()
    first = catalog.submit(record())
    assert catalog.submit(record()) == first
    assert catalog.count() == 1

@pytest.mark.parametrize("candidate", [
    record(lifecycle=AgentLifecycle.TESTED),
    record(passed=False),
    record(approved=False),
    record(tools=("repo.write",)),
    record(scopes=("repository:write",)),
])
def test_catalog_rejects_unreviewed_failed_or_privileged_candidates(candidate):
    with pytest.raises((PermissionError, ValueError)):
        PendingAgentCatalog().submit(candidate)

def test_catalog_rejects_duplicate_agent_name_with_different_artifacts():
    catalog = PendingAgentCatalog()
    catalog.submit(record())
    changed = record()
    changed_build = replace(changed.build, files=(GeneratedFile("agents/generated/a.py", "class B: pass"),
        GeneratedFile("tests/agents/generated/test_a.py", "def test_a(): assert True")))
    with pytest.raises(ValueError, match="already pending"):
        catalog.submit(replace(changed, build=changed_build))

def test_catalog_lookup_returns_only_pending_metadata():
    catalog = PendingAgentCatalog()
    item = catalog.submit(record())
    assert catalog.get(item.candidate_id) == item
    assert catalog.list_pending() == (item,)
