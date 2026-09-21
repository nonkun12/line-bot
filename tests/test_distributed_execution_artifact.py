import pytest

from core.distributed_execution_artifact import (
    ExecutionArtifact,
    StaticExecutionArtifactProvider,
)
from core.distributed_execution_gate import ExecutionIdentity


FULL_SHA = "a" * 40
DIGEST = "b" * 64


def _artifact() -> ExecutionArtifact:
    return ExecutionArtifact(
        identity=ExecutionIdentity("jobs", "0.2.0", FULL_SHA, DIGEST),
        artifact_id="artifact-jobs-1",
    )


def test_static_provider_returns_exact_artifact():
    artifact = _artifact()
    provider = StaticExecutionArtifactProvider((artifact,))

    assert provider.get("jobs") is artifact


def test_static_provider_fails_closed_for_unknown_agent():
    provider = StaticExecutionArtifactProvider((_artifact(),))

    with pytest.raises(PermissionError):
        provider.get("video")


def test_artifact_rejects_invalid_identity_shape():
    artifact = ExecutionArtifact(
        identity=ExecutionIdentity("jobs", "0.2.0", "A" * 40, DIGEST),
        artifact_id="artifact-jobs-1",
    )

    with pytest.raises(ValueError, match="lowercase"):
        artifact.validate()


def test_artifact_rejects_missing_artifact_id():
    artifact = ExecutionArtifact(
        identity=ExecutionIdentity("jobs", "0.2.0", FULL_SHA, DIGEST),
        artifact_id="",
    )

    with pytest.raises(ValueError, match="artifact_id"):
        artifact.validate()
