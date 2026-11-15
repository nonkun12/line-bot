import hashlib

import pytest

from core.ai_factory_stage147_artifact_evaluation import ArtifactManifest, verify_local_artifact
from core.ai_factory_stage148_local_runtime_adapters import (
    LocalModelBinding, LocalRuntimeAdapterRegistry, RuntimeAdapterError,
    RuntimeKind, RuntimeProbeResult, plan_candidate_output,
)


def binding(runtime=RuntimeKind.GGUF, fmt="gguf", quant="q4_k_m"):
    payload = b"local-model-fixture"
    manifest = ArtifactManifest(
        model_id="model-a", artifact_digest=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload), artifact_format=fmt, architecture="llama",
        tokenizer_fingerprint="tokenizer-v1", tensor_schema_fingerprint="tensors-v1",
        quantization=quant, license_id="reviewed", provenance="local-fixture",
        local_relative_path="models/model-a/model.bin",
    )
    proof = verify_local_artifact(manifest, (payload,))
    return LocalModelBinding("model-a", runtime, "model-a:latest", manifest, proof)


@pytest.mark.parametrize(
    "runtime,fmt,quant",
    [
        (RuntimeKind.OLLAMA, "gguf", "q4_k_m"),
        (RuntimeKind.MLX, "mlx", "4bit"),
        (RuntimeKind.MLX, "safetensors", "fp16"),
        (RuntimeKind.GGUF, "gguf", "q8_0"),
    ],
)
def test_supported_local_runtimes_create_read_only_probe_plans(runtime, fmt, quant):
    item = binding(runtime, fmt, quant)
    plan = LocalRuntimeAdapterRegistry().prepare_probe(item)
    assert plan.operation == "inspect_metadata"
    assert plan.local_only is True
    assert plan.read_only is True
    assert plan.network_allowed is False
    assert plan.shell_allowed is False
    assert plan.writes_allowed is False
    assert plan.execution_authorized is False
    assert len(plan.plan_digest) == 64


def test_runtime_probe_must_match_verified_artifact_and_metadata():
    item = binding()
    registry = LocalRuntimeAdapterRegistry()
    plan = registry.prepare_probe(item)
    result = RuntimeProbeResult(
        RuntimeKind.GGUF, "model-a", "model-a:latest",
        item.manifest.artifact_digest, "llama", "tokenizer-v1", "tensors-v1",
        "gguf", "q4_k_m", True, False, False,
    )
    registry.validate_probe_result(item, plan, result)


@pytest.mark.parametrize(
    "changes",
    [
        {"network_used": True},
        {"files_written": True},
        {"read_only": False},
        {"artifact_digest": "0" * 64},
        {"architecture": "other-arch"},
        {"tokenizer_fingerprint": "other-tokenizer"},
        {"quantization": "q8_0"},
    ],
)
def test_probe_rejects_identity_drift_or_side_effects(changes):
    item = binding()
    registry = LocalRuntimeAdapterRegistry()
    plan = registry.prepare_probe(item)
    values = dict(
        runtime=RuntimeKind.GGUF, model_id="model-a", runtime_model_ref="model-a:latest",
        artifact_digest=item.manifest.artifact_digest, architecture="llama",
        tokenizer_fingerprint="tokenizer-v1", tensor_schema_fingerprint="tensors-v1",
        artifact_format="gguf", quantization="q4_k_m",
        read_only=True, network_used=False, files_written=False,
    )
    values.update(changes)
    result = RuntimeProbeResult(**values)
    with pytest.raises(RuntimeAdapterError):
        registry.validate_probe_result(item, plan, result)


def test_runtime_rejects_format_mismatch_and_untrusted_reference():
    registry = LocalRuntimeAdapterRegistry()
    with pytest.raises(RuntimeAdapterError, match="format"):
        registry.prepare_probe(binding(RuntimeKind.GGUF, "safetensors", "fp16"))
    item = binding()
    unsafe = LocalModelBinding(
        item.model_id, item.runtime, "../../etc/passwd", item.manifest, item.verified_artifact
    )
    with pytest.raises(RuntimeAdapterError, match="unsafe"):
        registry.prepare_probe(unsafe)


def test_candidate_output_is_new_exclusive_and_not_authorized_to_write():
    plan = plan_candidate_output("child-148", ("a" * 64, "b" * 64))
    assert plan.destination_relative_path == "candidates/child-148/artifact.pending"
    assert plan.overwrite_existing is False
    assert plan.create_exclusive is True
    assert plan.execution_authorized is False


@pytest.mark.parametrize(
    "candidate,parents",
    [
        ("../bad", ("a" * 64, "b" * 64)),
        ("child", ("a" * 64,)),
        ("child", ("a" * 64, "a" * 64)),
        ("child", ("a" * 64, "z" * 64)),
    ],
)
def test_candidate_output_rejects_unsafe_ids_or_parent_digests(candidate, parents):
    with pytest.raises(RuntimeAdapterError):
        plan_candidate_output(candidate, parents)


def test_adapter_specs_never_claim_tensor_merge_support():
    registry = LocalRuntimeAdapterRegistry()
    for runtime in RuntimeKind:
        spec = registry.spec(runtime)
        assert spec.local_only is True
        assert spec.tensor_merge_supported is False
        assert spec.writes_during_probe is False
        assert spec.network_during_probe is False
