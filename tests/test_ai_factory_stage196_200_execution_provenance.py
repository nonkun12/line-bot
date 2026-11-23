from dataclasses import replace

import pytest

from core.ai_factory_stage191_195_capability_benchmarks import (
    BenchmarkCase, CaseResult, Stage191FrozenSuiteBuilder, Stage192RunEvidenceRecorder,
)
from core.ai_factory_stage196_200_execution_provenance import (
    ExecutionProvenanceError, Stage196ModelRuntimeManifest, Stage197DatasetProvenance,
    Stage198EnvironmentAttestor, Stage199ExecutionEvidenceBinder,
    Stage200ExecutionProvenanceGate, verify_model_runtime_manifest,
    verify_stage200_certificate,
)

SIGN = lambda digest: "signed:" + digest
VERIFY = lambda digest, signature: signature == SIGN(digest)
H = "a" * 64
J = "b" * 64
K = "c" * 64


def fixtures():
    suite = Stage191FrozenSuiteBuilder().build(
        "capability-suite", "v1",
        (BenchmarkCase("case-1", H, J, "reasoning", 1.0),),
        sign_suite=SIGN, verify_suite_signature=VERIFY,
    )
    run = Stage192RunEvidenceRecorder().build(
        suite, candidate_id="candidate-v2", artifact_digest=K, run_id="run-001",
        executor_id="runner-01", evaluator_id="evaluator-01",
        results=(CaseResult("case-1", .9, .99, 10, 100),),
        verify_suite_signature=VERIFY, sign_run=SIGN, verify_run_signature=VERIFY,
    )
    model = Stage196ModelRuntimeManifest().build(
        candidate_id="candidate-v2", artifact_digest=K, runtime_name="python",
        runtime_version="3.13.1", inference_engine="local-engine",
        inference_engine_version="1.2.0", runtime_image_digest=H,
        sign_manifest=SIGN, verify_manifest_signature=VERIFY,
    )
    dataset = Stage197DatasetProvenance().build(
        dataset_id="capability-data", dataset_version="v1", dataset_digest=J,
        source_manifest_digest=H, preprocessing_digest=K,
        license_or_usage_policy="approved-internal-evaluation",
        provenance_record_id="dataset-source-record-1",
        sign_manifest=SIGN, verify_manifest_signature=VERIFY,
    )
    environment = Stage198EnvironmentAttestor().build(
        environment_id="runner-env-01", operating_system="linux",
        architecture="x86_64", hardware_class="cpu-general",
        runtime_config_digest=H, dependency_lock_digest=J,
        attestation_level="self_reported", attestor_id="runner-01",
        sign_attestation=SIGN, verify_attestation_signature=VERIFY,
    )
    return suite, run, model, dataset, environment


def bind(values, **overrides):
    suite, run, model, dataset, environment = values
    args = dict(
        verify_suite_signature=VERIFY, verify_run_signature=VERIFY,
        verify_model_signature=VERIFY, verify_dataset_signature=VERIFY,
        verify_environment_signature=VERIFY, sign_binding=SIGN,
        verify_binding_signature=VERIFY, nonce="nonce-unique-001",
    )
    args.update(overrides)
    return Stage199ExecutionEvidenceBinder().build(
        suite, run, model_manifest=model, dataset_manifest=dataset,
        environment=environment, **args,
    )


def test_stage196_binds_artifact_and_runtime_identity():
    _, run, model, _, _ = fixtures()
    assert model.artifact_digest == run.artifact_digest
    assert model.manifest_digest
    forged = replace(model, runtime_version="9.9")
    assert not verify_model_runtime_manifest(forged, verify_signature=VERIFY)


def test_stage197_requires_dataset_source_and_preprocessing_digests():
    with pytest.raises(ExecutionProvenanceError, match="dataset source"):
        Stage197DatasetProvenance().build(
            dataset_id="data", dataset_version="v1", dataset_digest=H,
            source_manifest_digest="bad", preprocessing_digest=J,
            license_or_usage_policy="approved", provenance_record_id="source-1",
            sign_manifest=SIGN, verify_manifest_signature=VERIFY,
        )


def test_stage198_records_assurance_level_without_overclaiming():
    environment = fixtures()[-1]
    assert environment.attestation_level == "self_reported"
    with pytest.raises(ExecutionProvenanceError, match="HOLD"):
        Stage198EnvironmentAttestor().build(
            environment_id="env", operating_system="linux", architecture="x86_64",
            hardware_class="cpu", runtime_config_digest=H, dependency_lock_digest=J,
            attestation_level="self_reported", attestor_id="runner",
            sign_attestation=SIGN, verify_attestation_signature=VERIFY, hold_active=True,
        )


def test_stage199_binds_run_model_dataset_and_environment():
    binding = bind(fixtures())
    assert binding.run_digest and binding.dataset_digest == J
    assert binding.executor_id != binding.evaluator_id
    assert binding.proposal_only is True


def test_stage199_rejects_model_artifact_mismatch():
    suite, run, model, dataset, environment = fixtures()
    forged_model = replace(model, artifact_digest=H)
    with pytest.raises(ExecutionProvenanceError, match="artifact identity"):
        Stage199ExecutionEvidenceBinder().build(
            suite, run, model_manifest=forged_model, dataset_manifest=dataset,
            environment=environment, verify_suite_signature=VERIFY,
            verify_run_signature=VERIFY, verify_model_signature=VERIFY,
            verify_dataset_signature=VERIFY, verify_environment_signature=VERIFY,
            sign_binding=SIGN, verify_binding_signature=VERIFY, nonce="nonce-1",
        )


def test_stage199_can_require_hardware_signed_attestation():
    with pytest.raises(ExecutionProvenanceError, match="insufficient"):
        bind(fixtures(), require_hardware_signed=True)


def test_stage200_issues_only_proposal_certificate():
    binding = bind(fixtures())
    certificate = Stage200ExecutionProvenanceGate().build(
        binding, verify_binding_signature=VERIFY, sign_certificate=SIGN,
        verify_certificate_signature=VERIFY,
    )
    assert verify_stage200_certificate(certificate, verify_signature=VERIFY)
    assert certificate.proposal_only is True
    assert certificate.model_activation_authorized is False
    assert certificate.weight_mutation_authorized is False
    assert certificate.merge_deploy_authorized is False


def test_stage200_rejects_tampering_and_authority_escalation():
    binding = bind(fixtures())
    certificate = Stage200ExecutionProvenanceGate().build(
        binding, verify_binding_signature=VERIFY, sign_certificate=SIGN,
        verify_certificate_signature=VERIFY,
    )
    assert not verify_stage200_certificate(
        replace(certificate, artifact_digest=H), verify_signature=VERIFY,
    )
    assert not verify_stage200_certificate(
        replace(certificate, model_activation_authorized=True), verify_signature=VERIFY,
    )
    assert not verify_stage200_certificate(
        replace(certificate, nonce="replayed-nonce"), verify_signature=VERIFY,
    )


@pytest.mark.parametrize("stage", [196, 197, 198, 199, 200])
def test_hold_blocks_every_new_stage(stage):
    values = fixtures()
    suite, run, model, dataset, environment = values
    with pytest.raises(ExecutionProvenanceError, match="HOLD"):
        if stage == 196:
            Stage196ModelRuntimeManifest().build(
                candidate_id="candidate", artifact_digest=H, runtime_name="python",
                runtime_version="3.13", inference_engine="engine",
                inference_engine_version="1", runtime_image_digest=J,
                sign_manifest=SIGN, verify_manifest_signature=VERIFY, hold_active=True,
            )
        elif stage == 197:
            Stage197DatasetProvenance().build(
                dataset_id="data", dataset_version="v1", dataset_digest=H,
                source_manifest_digest=J, preprocessing_digest=K,
                license_or_usage_policy="approved", provenance_record_id="source-1",
                sign_manifest=SIGN, verify_manifest_signature=VERIFY, hold_active=True,
            )
        elif stage == 198:
            Stage198EnvironmentAttestor().build(
                environment_id="env", operating_system="linux", architecture="x86_64",
                hardware_class="cpu", runtime_config_digest=H, dependency_lock_digest=J,
                attestation_level="self_reported", attestor_id="runner",
                sign_attestation=SIGN, verify_attestation_signature=VERIFY, hold_active=True,
            )
        elif stage == 199:
            bind(values, hold_active=True)
        else:
            binding = bind(values)
            Stage200ExecutionProvenanceGate().build(
                binding, verify_binding_signature=VERIFY, sign_certificate=SIGN,
                verify_certificate_signature=VERIFY, hold_active=True,
            )
