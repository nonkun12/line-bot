"""Disposable Docker-backed runtime test gate for generated agent artifacts.

The runner executes only inside a pinned, network-disabled, read-only container.
It never imports generated code into the host Python process.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from .agent_factory import AgentBuild, AgentFactory, AgentTestReport


_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:+-]*@sha256:[0-9a-f]{64}$")
_MAX_OUTPUT = 12_000


class ProcessRunner(Protocol):
    def __call__(self, args: list[str], **kwargs): ...


class DockerSandbox:
    """Execute generated unittest files in a disposable hardened Docker container.

    Docker daemon, image and host kernel are part of the trust boundary. The
    image must be pinned by digest and contain Python plus the standard library.
    """

    def __init__(
        self,
        *,
        image: str,
        timeout_seconds: int = 30,
        memory_limit: str = "256m",
        cpu_limit: str = "1",
        pids_limit: int = 64,
        docker_binary: str = "docker",
        runner: ProcessRunner = subprocess.run,
    ) -> None:
        if not isinstance(image, str) or not _IMAGE.fullmatch(image):
            raise ValueError("sandbox image must be pinned by sha256 digest")
        if not 1 <= timeout_seconds <= 180:
            raise ValueError("timeout_seconds must be between 1 and 180")
        if memory_limit not in {"128m", "256m", "512m", "1g"}:
            raise ValueError("unsupported memory limit")
        if cpu_limit not in {"0.5", "1", "2"}:
            raise ValueError("unsupported CPU limit")
        if not 16 <= pids_limit <= 128:
            raise ValueError("pids_limit must be between 16 and 128")
        if not docker_binary or any(ch.isspace() for ch in docker_binary):
            raise ValueError("docker_binary must be a single executable path")
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.pids_limit = pids_limit
        self.docker_binary = docker_binary
        self.runner = runner

    def test(self, build: AgentBuild) -> AgentTestReport:
        if not isinstance(build, AgentBuild):
            return AgentTestReport(False, (), ("invalid AgentBuild",))
        try:
            AgentFactory._validate_files(build.files)
        except (TypeError, ValueError) as exc:
            return AgentTestReport(False, (), (f"artifact validation failed: {exc}",))

        try:
            with tempfile.TemporaryDirectory(prefix="ai-agent-sandbox-") as temp:
                workspace = Path(temp) / "workspace"
                workspace.mkdir(mode=0o755)
                for artifact in build.files:
                    relative = Path(artifact.path.replace("\\", "/"))
                    target = workspace / relative
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                    target.write_text(artifact.content, encoding="utf-8")
                    target.chmod(0o444)
                for directory, _, _ in os.walk(workspace, topdown=False):
                    Path(directory).chmod(0o555)
                workspace.chmod(0o555)
                command = [
                    self.docker_binary, "run", "--rm",
                    "--network=none",
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    f"--pids-limit={self.pids_limit}",
                    f"--memory={self.memory_limit}",
                    f"--cpus={self.cpu_limit}",
                    "--user=65534:65534",
                    "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
                    "--mount", f"type=bind,src={workspace},dst=/workspace,readonly",
                    self.image,
                    "python", "-I", "-c",
                    "import sys,unittest; sys.path.insert(0, '/workspace'); "
                    "suite=unittest.defaultTestLoader.discover("
                    "'/workspace/tests/agents/generated', pattern='test_*.py'); "
                    "result=unittest.TextTestRunner(verbosity=2).run(suite); "
                    "sys.exit(0 if result.wasSuccessful() and result.testsRun else 1)",
                ]
                completed = self.runner(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"},
                )
        except subprocess.TimeoutExpired:
            return AgentTestReport(False, (), ("sandbox timed out; candidate blocked",))
        except (OSError, subprocess.SubprocessError) as exc:
            return AgentTestReport(
                False, (), (f"sandbox infrastructure failure: {type(exc).__name__}",)
            )

        stdout = (completed.stdout or "")[-_MAX_OUTPUT:]
        stderr = (completed.stderr or "")[-_MAX_OUTPUT:]
        if completed.returncode != 0:
            details = (stderr or stdout or "container returned non-zero exit status").strip()
            return AgentTestReport(
                False,
                (f"container image digest: {self.image.rsplit('@', 1)[1]}",),
                (f"isolated unittest suite failed (exit={completed.returncode}): {details}",),
            )
        if "Ran 0 tests" in stdout + stderr:
            return AgentTestReport(False, (), ("sandbox discovered zero tests; candidate blocked",))
        return AgentTestReport(
            True,
            (
                f"container image digest: {self.image.rsplit('@', 1)[1]}",
                "network disabled; read-only root and artifact mount; capabilities dropped",
                f"resource limits: memory={self.memory_limit}, cpus={self.cpu_limit}, pids={self.pids_limit}",
                (stdout or stderr or "unittest suite exited successfully")[-2000:],
            ),
            (),
        )


__all__ = ["DockerSandbox"]
