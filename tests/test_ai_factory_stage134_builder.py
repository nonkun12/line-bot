import json

import pytest

from core.agent_factory import AgentBuild, GeneratedFile
from core.agent_specs import AgentSpec
from core.ai_factory_stage134_builder import (
    BuilderLimits,
    OllamaAgentBuilder,
    StaticAgentSandbox,
)


class FakeModel:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def chat(self, *, system, prompt):
        self.calls.append((system, prompt))
        return self.content


def spec():
    return AgentSpec.create(
        name="repo-auditor",
        purpose="Read-only repository audit",
        input_contract="Diff plus evidence",
        output_contract="Findings",
        safety_constraints=("read only",),
        tests=("reject_missing_evidence",),
    )


def payload(source="class Auditor:\n    pass\n", test="def test_contract():\n    assert True\n"):
    return json.dumps({"files": [
        {"path": "agents/generated/repo_auditor.py", "content": source},
        {"path": "tests/agents/generated/test_repo_auditor.py", "content": test},
    ]})


def test_builder_returns_inert_bounded_artifacts_without_writing_or_execution():
    client = FakeModel(payload())
    result = OllamaAgentBuilder(client).build(spec())
    assert result.spec == spec()
    assert len(result.files) == 2
    assert client.calls
    assert all(isinstance(item, GeneratedFile) for item in result.files)


@pytest.mark.parametrize("raw", [
    "not-json",
    '{"unexpected":[]}',
    '{"files":[{"path":"agents/generated/a.py","content":"x"}]}',
    '{"files":[{"path":"../escape.py","content":"x"},{"path":"tests/agents/generated/t.py","content":"x"}]}',
])
def test_builder_rejects_malformed_or_unsafe_artifacts(raw):
    with pytest.raises(ValueError):
        OllamaAgentBuilder(FakeModel(raw)).build(spec())


def test_builder_enforces_file_and_total_size_limits():
    raw = payload(source="x" * 101)
    with pytest.raises(ValueError, match="per-file"):
        OllamaAgentBuilder(FakeModel(raw), BuilderLimits(max_file_chars=100)).build(spec())


def test_static_sandbox_parses_without_executing_generated_code():
    result = StaticAgentSandbox().test(AgentBuild(
        spec=spec(),
        files=(
            GeneratedFile("agents/generated/a.py", "class A: pass"),
            GeneratedFile("tests/agents/generated/test_a.py", "def test_a(): assert True"),
        ),
    ))
    assert result.passed
    assert len(result.evidence) == 2


@pytest.mark.parametrize("source", [
    "import subprocess",
    "from pathlib import Path",
    "def run():\n    eval('1 + 1')",
    "def read():\n    open('/tmp/x')",
])
def test_static_sandbox_rejects_dangerous_imports_and_calls(source):
    result = StaticAgentSandbox().test(AgentBuild(
        spec=spec(),
        files=(
            GeneratedFile("agents/generated/a.py", source),
            GeneratedFile("tests/agents/generated/test_a.py", "def test_a(): assert True"),
        ),
    ))
    assert not result.passed
    assert result.failures


def test_static_sandbox_rejects_syntax_errors():
    result = StaticAgentSandbox().test(AgentBuild(
        spec=spec(),
        files=(
            GeneratedFile("agents/generated/a.py", "def broken(:"),
            GeneratedFile("tests/agents/generated/test_a.py", "def test_a(): assert True"),
        ),
    ))
    assert not result.passed
