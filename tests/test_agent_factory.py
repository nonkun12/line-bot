import pytest

from core.agent_factory import (
    AgentBuild,
    AgentFactory,
    AgentReviewReport,
    AgentTestReport,
    GeneratedFile,
)
from core.agent_specs import AgentLifecycle, AgentSpec
from core.agent_versioning import AgentVersion


def make_spec(*, tools=(), scopes=()):
    return AgentSpec.create(
        name="generated_researcher",
        purpose="research a bounded topic",
        input_contract="topic string",
        output_contract="evidence-backed summary",
        allowed_tools=tools,
        resource_scope=scopes,
        safety_constraints=("read-only", "no permission escalation", "no deployment"),
        tests=("tests/agents/generated/test_researcher.py",),
    )


class Architect:
    def __init__(self, spec=None):
        self.spec = spec or make_spec()

    def design(self, capability_gap):
        assert capability_gap
        return self.spec


class Builder:
    def __init__(self, files=None):
        self.files = files or (
            GeneratedFile("agents/generated/researcher.py", "class Researcher: pass"),
            GeneratedFile("tests/agents/generated/test_researcher.py", "def test_contract(): assert True"),
        )

    def build(self, spec):
        return AgentBuild(spec, self.files)


class Sandbox:
    def __init__(self, report=None):
        self.report = report or AgentTestReport(True, ("isolated test run: passed",))

    def test(self, build):
        return self.report


class Reviewer:
    def __init__(self, report=None):
        self.report = report or AgentReviewReport(True, ("scope checked",))

    def review(self, build, tests):
        return self.report


class ApprovalGate:
    def __init__(self, approved=True):
        self.approved = approved

    def approve(self, candidate, approved_by):
        return self.approved


class RuntimeAgent:
    name = "generated_researcher"
    description = "generated candidate"
    priority = 1
    enabled = True

    def can_handle(self, request):
        return False

    def handle(self, request):
        raise NotImplementedError


def factory(**kwargs):
    adapters = {
        "architect": Architect(),
        "builder": Builder(),
        "sandbox": Sandbox(),
        "reviewer": Reviewer(),
    }
    adapters.update(kwargs)
    return AgentFactory(**adapters)


def test_candidate_requires_all_gates_and_is_not_registered_automatically():
    subject = factory()
    record = subject.create_candidate("missing research specialist")
    assert record.lifecycle == AgentLifecycle.REVIEWED
    assert subject.candidate_names() == ("generated_researcher",)
    assert subject.governance.names() == ()


def test_empty_gap_is_rejected_before_architect_runs():
    with pytest.raises(ValueError, match="capability_gap"):
        factory().create_candidate("  ")


def test_architect_cannot_self_select_enabled_lifecycle():
    subject = factory(architect=Architect(make_spec()))
    subject.architect.spec = AgentSpec.create(
        name="generated_researcher",
        purpose="research",
        input_contract="topic",
        output_contract="summary",
        safety_constraints=("read-only",),
        tests=("test",),
        lifecycle=AgentLifecycle.ENABLED,
    )
    with pytest.raises(ValueError, match="GENERATED"):
        subject.create_candidate("research")


def test_tool_and_scope_expansion_fail_closed():
    subject = AgentFactory(
        architect=Architect(make_spec(tools=("repo.write",))),
        builder=Builder(),
        sandbox=Sandbox(),
        reviewer=Reviewer(),
    )
    with pytest.raises(PermissionError, match="tools outside"):
        subject.create_candidate("write capability")

    scoped = AgentFactory(
        architect=Architect(make_spec(scopes=("production",))),
        builder=Builder(),
        sandbox=Sandbox(),
        reviewer=Reviewer(),
    )
    with pytest.raises(PermissionError, match="resource scopes"):
        scoped.create_candidate("production access")


def test_builder_cannot_escape_generated_directories():
    files = (
        GeneratedFile("../core/unsafe.py", "pass"),
        GeneratedFile("tests/agents/generated/test_unsafe.py", "def test_it(): pass"),
    )
    with pytest.raises(ValueError, match="outside the factory sandbox"):
        factory(builder=Builder(files)).create_candidate("unsafe path")


def test_sandbox_failure_prevents_candidate_registration():
    subject = factory(sandbox=Sandbox(AgentTestReport(False, (), ("failed",))))
    with pytest.raises(ValueError, match="sandbox tests"):
        subject.create_candidate("failing candidate")
    assert subject.candidate_names() == ()


def test_review_blocker_prevents_candidate_registration():
    subject = factory(reviewer=Reviewer(AgentReviewReport(False, (), ("unsafe",))))
    with pytest.raises(ValueError, match="review did not approve"):
        subject.create_candidate("blocked candidate")
    assert subject.candidate_names() == ()


def test_registration_requires_a_configured_human_approval_gate():
    subject = factory()
    subject.create_candidate("research")
    with pytest.raises(PermissionError, match="gate is not configured"):
        subject.approve_and_register(
            "generated_researcher",
            agent=RuntimeAgent(),
            version=AgentVersion("generated_researcher", "1.0.0"),
            approved_by="operator",
        )
    assert subject.governance.names() == ()


def test_rejected_human_approval_gate_prevents_registration():
    subject = factory(approval_gate=ApprovalGate(False))
    subject.create_candidate("research")
    with pytest.raises(PermissionError, match="gate rejected"):
        subject.approve_and_register(
            "generated_researcher",
            agent=RuntimeAgent(),
            version=AgentVersion("generated_researcher", "1.0.0"),
            approved_by="operator",
        )
    assert subject.governance.names() == ()


def test_human_approved_candidate_is_registered_through_governance():
    subject = factory(approval_gate=ApprovalGate(True))
    subject.create_candidate("research")
    result = subject.approve_and_register(
        "generated_researcher",
        agent=RuntimeAgent(),
        version=AgentVersion("generated_researcher", "1.0.0"),
        approved_by="human operator",
    )
    assert result.name == "generated_researcher"
    assert subject.governance.names() == ("generated_researcher",)
    assert subject.get_candidate("generated_researcher").lifecycle == AgentLifecycle.ENABLED
