"""Stage 148: local runtime adapter contracts and isolated execution planning.

The adapters are declarative and local-only. They create inspect/probe plans,
not subprocesses. A caller must supply a separately reviewed local executor.
No runtime is contacted, no model is loaded, and no weights are changed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import re

from .ai_factory_stage147_artifact_evaluation import ArtifactManifest, VerifiedArtifact


class RuntimeKind(str, Enum):
    OLLAMA = "ollama"
    MLX = "mlx"
    GGUF = "gguf"


class RuntimeAdapterError(ValueError):
    """Raised when a local runtime request violates the adapter contract."""


@dataclass(frozen=True)
class RuntimeAdapterSpec:
    runtime: RuntimeKind
    accepted_formats: tuple[str, ...]
    local_only: bool
    metadata_probe_supported: bool
    inference_supported: bool
    tensor_merge_supported: bool
    writes_during_probe: bool
    network_during_probe: bool


@dataclass(frozen=True)
class LocalModelBinding:
    model_id: str
    runtime: RuntimeKind
    runtime_model_ref: str
    manifest: ArtifactManifest
    verified_artifact: VerifiedArtifact


@dataclass(frozen=True)
class LocalProbePlan:
    runtime: RuntimeKind
    model_id: str
    runtime_model_ref: str
    operation: str
    expected_artifact_digest: str
    expected_manifest_digest: str
    accepted_formats: tuple[str, ...]
    local_only: bool
    read_only: bool
    network_allowed: bool
    shell_allowed: bool
    writes_allowed: bool
    execution_authorized: bool
    plan_digest: str


@dataclass(frozen=True)
class RuntimeProbeResult:
    runtime: RuntimeKind
    model_id: str
    runtime_model_ref: str
    artifact_digest: str
    architecture: str
    tokenizer_fingerprint: str
    tensor_schema_fingerprint: str
    artifact_format: str
    quantization: str
    read_only: bool
    network_used: bool
    files_written: bool


@dataclass(frozen=True)
class CandidateOutputPlan:
    candidate_id: str
    parent_artifact_digests: tuple[str, ...]
    destination_relative_path: str
    overwrite_existing: bool
    create_exclusive: bool
    execution_authorized: bool
    reason: str


_SPECS = {
    RuntimeKind.OLLAMA: RuntimeAdapterSpec(
        RuntimeKind.OLLAMA, ("gguf", "ollama_blob"), True, True, True, False, False, False
    ),
    RuntimeKind.MLX: RuntimeAdapterSpec(
        RuntimeKind.MLX, ("mlx", "safetensors"), True, True, True, False, False, False
    ),
    RuntimeKind.GGUF: RuntimeAdapterSpec(
        RuntimeKind.GGUF, ("gguf",), True, True, True, False, False, False
    ),
}
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


class LocalRuntimeAdapterRegistry:
    """Builds least-privilege plans for Ollama, MLX and standalone GGUF runtimes."""

    def spec(self, runtime: RuntimeKind) -> RuntimeAdapterSpec:
        try:
            return _SPECS[runtime]
        except (KeyError, TypeError) as exc:
            raise RuntimeAdapterError("unsupported local runtime") from exc

    def prepare_probe(self, binding: LocalModelBinding) -> LocalProbePlan:
        if not isinstance(binding, LocalModelBinding):
            raise RuntimeAdapterError("typed local model binding is required")
        spec = self.spec(binding.runtime)
        manifest = binding.manifest
        proof = binding.verified_artifact
        if not spec.local_only or not spec.metadata_probe_supported:
            raise RuntimeAdapterError("runtime does not provide a local metadata probe")
        if binding.model_id != manifest.model_id or proof.model_id != manifest.model_id:
            raise RuntimeAdapterError("model identity differs across runtime, manifest and byte proof")
        if proof.artifact_digest != manifest.artifact_digest or proof.byte_length != manifest.byte_length:
            raise RuntimeAdapterError("verified artifact does not match the exact manifest")
        if not _SAFE_REF.fullmatch(binding.runtime_model_ref or ""):
            raise RuntimeAdapterError("runtime model reference contains unsafe characters")
        if manifest.artifact_format not in spec.accepted_formats:
            raise RuntimeAdapterError("artifact format is not supported by this runtime adapter")
        if not manifest.local_relative_path or manifest.local_relative_path.startswith("/"):
            raise RuntimeAdapterError("artifact must use a local relative path")
        fields = (
            binding.runtime.value, binding.model_id, binding.runtime_model_ref,
            manifest.artifact_digest, proof.manifest_digest, manifest.artifact_format,
            "inspect_metadata", "read_only", "network_disabled", "shell_disabled",
        )
        digest = hashlib.sha256("\\0".join(fields).encode("utf-8")).hexdigest()
        return LocalProbePlan(
            binding.runtime, binding.model_id, binding.runtime_model_ref,
            "inspect_metadata", manifest.artifact_digest, proof.manifest_digest,
            spec.accepted_formats, True, True, False, False, False, False, digest,
        )

    def validate_probe_result(
        self, binding: LocalModelBinding, plan: LocalProbePlan, result: RuntimeProbeResult
    ) -> None:
        if not isinstance(plan, LocalProbePlan) or not isinstance(result, RuntimeProbeResult):
            raise RuntimeAdapterError("typed probe plan and result are required")
        if plan.execution_authorized or not plan.read_only or plan.network_allowed or plan.writes_allowed:
            raise RuntimeAdapterError("probe plan violates the read-only execution boundary")
        if (result.runtime != binding.runtime or result.model_id != binding.model_id
                or result.runtime_model_ref != binding.runtime_model_ref):
            raise RuntimeAdapterError("runtime probe identity mismatch")
        if result.artifact_digest != binding.manifest.artifact_digest:
            raise RuntimeAdapterError("runtime probe artifact digest mismatch")
        if not result.read_only or result.network_used or result.files_written:
            raise RuntimeAdapterError("runtime probe performed a forbidden side effect")
        expected = binding.manifest
        actual_fields = (
            (result.architecture, expected.architecture),
            (result.tokenizer_fingerprint, expected.tokenizer_fingerprint),
            (result.tensor_schema_fingerprint, expected.tensor_schema_fingerprint),
            (result.artifact_format, expected.artifact_format),
            (result.quantization, expected.quantization),
        )
        if any(actual != wanted for actual, wanted in actual_fields):
            raise RuntimeAdapterError("runtime metadata differs from the verified artifact manifest")


def plan_candidate_output(
    candidate_id: str, parent_artifact_digests: tuple[str, ...]
) -> CandidateOutputPlan:
    """Propose a new exclusive destination; this function does not create it."""
    if not _SAFE_ID.fullmatch(candidate_id or ""):
        raise RuntimeAdapterError("candidate ID is unsafe")
    if not isinstance(parent_artifact_digests, tuple) or len(parent_artifact_digests) < 2:
        raise RuntimeAdapterError("at least two parent digests are required")
    if any(not re.fullmatch(r"[0-9a-f]{64}", digest or "") for digest in parent_artifact_digests):
        raise RuntimeAdapterError("parent digests must be lowercase SHA-256")
    if len(set(parent_artifact_digests)) != len(parent_artifact_digests):
        raise RuntimeAdapterError("parent artifacts must be distinct")
    return CandidateOutputPlan(
        candidate_id, parent_artifact_digests,
        f"candidates/{candidate_id}/artifact.pending",
        False, True, False,
        "new exclusive destination only; no parent overwrite and no write until separately approved",
    )


__all__ = [
    "RuntimeKind", "RuntimeAdapterError", "RuntimeAdapterSpec",
    "LocalModelBinding", "LocalProbePlan", "RuntimeProbeResult",
    "CandidateOutputPlan", "LocalRuntimeAdapterRegistry", "plan_candidate_output",
]
