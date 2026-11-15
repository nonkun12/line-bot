import json
import pytest
from core.agent_factory import AgentBuild, AgentTestReport, GeneratedFile
from core.agent_specs import AgentSpec
from core.ai_factory_stage136_reviewer import OllamaAgentReviewer, require_independent_review_client

class FakeModel:
    def __init__(self, response): self.response, self.prompts = response, []
    def chat(self, *, system, prompt): self.prompts.append((system, prompt)); return self.response

def build():
    spec = AgentSpec.create(name="auditor", purpose="Read-only audit", input_contract="diff",
        output_contract="findings", safety_constraints=("read-only",), tests=("test-x",))
    return AgentBuild(spec, (GeneratedFile("agents/generated/auditor.py", "class Auditor: pass"),
        GeneratedFile("tests/agents/generated/test_auditor.py", "def test_auditor(): assert True")))

def report(): return AgentTestReport(True, ("container test suite passed",), ())

def test_reviewer_accepts_strict_review_and_binds_artifact_digest():
    client = FakeModel(json.dumps({"approved": True, "findings": ["least privilege OK"], "blockers": []}))
    result = OllamaAgentReviewer(client).review(build(), report())
    assert result.approved
    assert any("reviewed_artifact_sha256=" in item for item in result.findings)
    assert build().files[0].content in client.prompts[0][1]

def test_reviewer_downgrades_approval_when_blockers_are_reported():
    client = FakeModel(json.dumps({"approved": True, "findings": [], "blockers": ["unsafe IO"]}))
    result = OllamaAgentReviewer(client).review(build(), report())
    assert not result.approved and result.blockers == ("unsafe IO",)

def test_reviewer_rejects_malformed_or_unbounded_output():
    for raw in ("not-json", '{"approved":"yes","findings":[],"blockers":[]}',
                json.dumps({"approved": True, "findings": ["x"], "blockers": [], "extra": 1})):
        with pytest.raises(ValueError): OllamaAgentReviewer(FakeModel(raw)).review(build(), report())

def test_reviewer_does_not_review_failed_sandbox():
    client = FakeModel("{}")
    result = OllamaAgentReviewer(client).review(build(), AgentTestReport(False, (), ("test failed",)))
    assert not result.approved and not client.prompts and result.blockers

def test_builder_cannot_review_its_own_output():
    client = FakeModel("{}")
    with pytest.raises(ValueError, match="distinct"):
        require_independent_review_client(client, OllamaAgentReviewer(client))

def test_separate_builder_and_reviewer_clients_are_accepted():
    require_independent_review_client(FakeModel("{}"), OllamaAgentReviewer(FakeModel("{}")))
