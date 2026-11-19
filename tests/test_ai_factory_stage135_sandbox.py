import subprocess

from core.agent_factory import AgentBuild, GeneratedFile
from core.agent_specs import AgentSpec
from core.ai_factory_stage135_sandbox import DockerSandbox


IMAGE = "python:3.13-slim@sha256:" + "a" * 64


def build():
    spec = AgentSpec.create(
        name="sample-agent",
        purpose="Sample",
        input_contract="Input",
        output_contract="Output",
        safety_constraints=("read only",),
        tests=("test_contract",),
    )
    return AgentBuild(spec, (
        GeneratedFile("agents/generated/sample.py", "class Sample: pass"),
        GeneratedFile(
            "tests/agents/generated/test_sample.py",
            "import unittest\nclass TestSample(unittest.TestCase):\n"
            "    def test_contract(self): self.assertTrue(True)\n",
        ),
    ))


class Result:
    def __init__(self, code=0, stdout="Ran 1 test", stderr=""):
        self.returncode, self.stdout, self.stderr = code, stdout, stderr


def test_requires_digest_pinned_image():
    try:
        DockerSandbox(image="python:latest")
    except ValueError as exc:
        assert "sha256" in str(exc)
    else:
        raise AssertionError("unpinned image must be rejected")


def test_builds_hardened_container_command_and_returns_evidence():
    calls = []
    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return Result()
    report = DockerSandbox(image=IMAGE, runner=runner).test(build())
    assert report.passed
    args, kwargs = calls[0]
    assert "--network=none" in args
    assert "--read-only" in args
    assert "--cap-drop=ALL" in args
    assert "--security-opt=no-new-privileges" in args
    assert kwargs["timeout"] == 30
    assert kwargs["shell"] if "shell" in kwargs else True
    assert any("readonly" in item for item in args)


def test_nonzero_exit_blocks_candidate():
    report = DockerSandbox(
        image=IMAGE,
        runner=lambda *a, **k: Result(1, stderr="AssertionError"),
    ).test(build())
    assert not report.passed
    assert "AssertionError" in report.failures[0]


def test_zero_discovered_tests_blocks_candidate():
    report = DockerSandbox(
        image=IMAGE,
        runner=lambda *a, **k: Result(0, stdout="Ran 0 tests"),
    ).test(build())
    assert not report.passed


def test_timeout_and_infrastructure_errors_fail_closed():
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)
    assert not DockerSandbox(image=IMAGE, runner=timeout).test(build()).passed
    def missing(*args, **kwargs):
        raise FileNotFoundError("docker")
    report = DockerSandbox(image=IMAGE, runner=missing).test(build())
    assert not report.passed
    assert "infrastructure failure" in report.failures[0]


def test_invalid_artifact_path_is_rejected_before_container_call():
    candidate = AgentBuild(build().spec, (
        GeneratedFile("../escape.py", "pass"),
        GeneratedFile("tests/agents/generated/test_x.py", "pass"),
    ))
    called = []
    report = DockerSandbox(image=IMAGE, runner=lambda *a, **k: called.append(a)).test(candidate)
    assert not report.passed
    assert not called
