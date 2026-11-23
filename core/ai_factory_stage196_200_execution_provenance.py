"""Stages 196-200: verifiable execution provenance for capability benchmarks.

These stages validate signed provenance claims and bind them to existing Stage 192
run evidence. Signatures attest to supplied claims; they do not by themselves prove
physical execution, isolation, or hardware truth.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Callable


_HEX = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$")
_ALLOWED_ATTESTATION_LEVELS = {"self_reported", "hardware_signed"}


class ExecutionProvenanceError(ValueError):
    """Raised when execution provenance is incomplete, inconsistent, or replayed."""


def _digest(payload: object) -> str:
    try:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExecutionProvenanceError("provenance payload is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _check_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ExecutionProvenanceError(f"{label} is invalid")


def _check_digest(value: str, label: str) -> None:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise ExecutionProvenanceError(f"{label} must be a lowercase SHA-256 digest")


def _check_signature(digest: str, signature: str,
                     verifier: Callable[[str, str], bool], label: str) -> None:
    _check_digest(digest, label + " digest")
    if not isinstance(signature, str) or not signature or not callable(verifier):
        raise ExecutionProvenanceError(f"{label} signature or verifier is missing")
    try:
        valid = verifier(digest, signature)
    except Exception as exc:
        raise ExecutionProvenanceError(f"{label} signature verification failed") from exc
    if valid is not True:
        raise ExecutionProvenanceError(f"{label} signature verification failed")


def _sign(digest: str, signer: Callable[[str], str], label: str) -> str:
    if not callable(signer):
        raise ExecutionProvenanceError(f"{label} signer is missing")
    try:
        signature = signer(digest)
    except Exception as exc:
        raise ExecutionProvenanceError(f"{label} signing failed") from exc
    if not isinstance(signature, str) or not signature:
        raise ExecutionProvenanceError(f"{label} signing returned an empty signature")
    return signature


def _hold(hold_active: bool, stage: int) -> None:
    if hold_active:
        raise ExecutionProvenanceError(f"HOLD blocks Stage {stage}")


@dataclass(frozen=True)
class ModelRuntimeManifest:
    candidate_id: str
    artifact_digest: str
    runtime_name: str
    runtime_version: str
    inference_engine: str
    inference_engine_version: str
    runtime_image_digest: str
    manifest_digest: str
    signature: str
    proposal_only: bool = True


def _model_payload(candidate_id: str, artifact_digest: str, runtime_name: str,
                   runtime_version: str, inference_engine: str,
                   inference_engine_version: str, runtime_image_digest: str) -> dict:
    return {
        "candidate_id": candidate_id, "artifact_digest": artifact_digest,
        "runtime_name": runtime_name, "runtime_version": runtime_version,
        "inference_engine": inference_engine,
        "inference_engine_version": inference_engine_version,
        "runtime_image_digest": runtime_image_digest, "proposal_only": True,
    }


class Stage196ModelRuntimeManifest:
    """Identify exact model bytes and the declared software stack used to run them."""

    def build(self, *, candidate_id: str, artifact_digest: str, runtime_name: str,
              runtime_version: str, inference_engine: str,
              inference_engine_version: str, runtime_image_digest: str,
              sign_manifest: Callable[[str], str],
              verify_manifest_signature: Callable[[str, str], bool],
              hold_active: bool = False) -> ModelRuntimeManifest:
        _hold(hold_active, 196)
        for value, label in (
            (candidate_id, "candidate id"), (runtime_name, "runtime name"),
            (runtime_version, "runtime version"), (inference_engine, "inference engine"),
            (inference_engine_version, "inference engine version"),
        ):
            _check_id(value, label)
        _check_digest(artifact_digest, "model artifact")
        _check_digest(runtime_image_digest, "runtime image")
        digest = _digest(_model_payload(candidate_id, artifact_digest, runtime_name,
                                        runtime_version, inference_engine,
                                        inference_engine_version, runtime_image_digest))
        signature = _sign(digest, sign_manifest, "model/runtime manifest")
        _check_signature(digest, signature, verify_manifest_signature, "model/runtime manifest")
        return ModelRuntimeManifest(candidate_id, artifact_digest, runtime_name, runtime_version,
                                     inference_engine, inference_engine_version,
                                     runtime_image_digest, digest, signature)


def verify_model_runtime_manifest(manifest: ModelRuntimeManifest, *,
                                  verify_signature: Callable[[str, str], bool]) -> bool:
    if not isinstance(manifest, ModelRuntimeManifest) or manifest.proposal_only is not True:
        return False
    payload = _model_payload(manifest.candidate_id, manifest.artifact_digest,
                              manifest.runtime_name, manifest.runtime_version,
                              manifest.inference_engine, manifest.inference_engine_version,
                              manifest.runtime_image_digest)
    if _digest(payload) != manifest.manifest_digest:
        return False
    try:
        _check_signature(manifest.manifest_digest, manifest.signature,
                         verify_signature, "model/runtime manifest")
    except ExecutionProvenanceError:
        return False
    return True


@dataclass(frozen=True)
class DatasetProvenanceManifest:
    dataset_id: str
    dataset_version: str
    dataset_digest: str
    source_manifest_digest: str
    preprocessing_digest: str
    license_or_usage_policy: str
    provenance_record_id: str
    manifest_digest: str
    signature: str
    frozen: bool = True
    proposal_only: bool = True


def _dataset_payload(dataset_id: str, dataset_version: str, dataset_digest: str,
                     source_manifest_digest: str, preprocessing_digest: str,
                     license_or_usage_policy: str, provenance_record_id: str) -> dict:
    return {
        "dataset_id": dataset_id, "dataset_version": dataset_version,
        "dataset_digest": dataset_digest, "source_manifest_digest": source_manifest_digest,
        "preprocessing_digest": preprocessing_digest,
        "license_or_usage_policy": license_or_usage_policy,
        "provenance_record_id": provenance_record_id,
        "frozen": True, "proposal_only": True,
    }


class Stage197DatasetProvenance:
    """Bind a frozen dataset snapshot to source, preprocessing, and usage-policy records."""

    def build(self, *, dataset_id: str, dataset_version: str, dataset_digest: str,
              source_manifest_digest: str, preprocessing_digest: str,
              license_or_usage_policy: str, provenance_record_id: str,
              sign_manifest: Callable[[str], str],
              verify_manifest_signature: Callable[[str, str], bool],
              hold_active: bool = False) -> DatasetProvenanceManifest:
        _hold(hold_active, 197)
        for value, label in (
            (dataset_id, "dataset id"), (dataset_version, "dataset version"),
            (license_or_usage_policy, "license/usage policy"),
            (provenance_record_id, "provenance record id"),
        ):
            _check_id(value, label)
        for value, label in (
            (dataset_digest, "dataset"), (source_manifest_digest, "dataset source manifest"),
            (preprocessing_digest, "dataset preprocessing"),
        ):
            _check_digest(value, label)
        digest = _digest(_dataset_payload(dataset_id, dataset_version, dataset_digest,
                                          source_manifest_digest, preprocessing_digest,
                                          license_or_usage_policy, provenance_record_id))
        signature = _sign(digest, sign_manifest, "dataset provenance")
        _check_signature(digest, signature, verify_manifest_signature, "dataset provenance")
        return DatasetProvenanceManifest(
            dataset_id, dataset_version, dataset_digest, source_manifest_digest,
            preprocessing_digest, license_or_usage_policy, provenance_record_id,
            digest, signature,
        )


def verify_dataset_provenance(manifest: DatasetProvenanceManifest, *,
                              verify_signature: Callable[[str, str], bool]) -> bool:
    if (not isinstance(manifest, DatasetProvenanceManifest)
            or manifest.frozen is not True or manifest.proposal_only is not True):
        return False
    payload = _dataset_payload(
        manifest.dataset_id, manifest.dataset_version, manifest.dataset_digest,
        manifest.source_manifest_digest, manifest.preprocessing_digest,
        manifest.license_or_usage_policy, manifest.provenance_record_id,
    )
    if _digest(payload) != manifest.manifest_digest:
        return False
    try:
        _check_signature(manifest.manifest_digest, manifest.signature,
                         verify_signature, "dataset provenance")
    except ExecutionProvenanceError:
        return False
    return True


@dataclass(frozen=True)
class ExecutionEnvironmentAttestation:
    environment_id: str
    operating_system: str
    architecture: str
    hardware_class: str
    runtime_config_digest: str
    dependency_lock_digest: str
    attestation_level: str
    attestor_id: str
    environment_digest: str
    signature: str
    proposal_only: bool = True


def _environment_payload(environment_id: str, operating_system: str, architecture: str,
                         hardware_class: str, runtime_config_digest: str,
                         dependency_lock_digest: str, attestation_level: str,
                         attestor_id: str) -> dict:
    return {
        "environment_id": environment_id, "operating_system": operating_system,
        "architecture": architecture, "hardware_class": hardware_class,
        "runtime_config_digest": runtime_config_digest,
        "dependency_lock_digest": dependency_lock_digest,
        "attestation_level": attestation_level, "attestor_id": attestor_id,
        "proposal_only": True,
    }


class Stage198EnvironmentAttestor:
    """Record a privacy-minimized environment fingerprint and its assurance level."""

    def build(self, *, environment_id: str, operating_system: str, architecture: str,
              hardware_class: str, runtime_config_digest: str,
              dependency_lock_digest: str, attestation_level: str, attestor_id: str,
              sign_attestation: Callable[[str], str],
              verify_attestation_signature: Callable[[str, str], bool],
              hold_active: bool = False) -> ExecutionEnvironmentAttestation:
        _hold(hold_active, 198)
        for value, label in (
            (environment_id, "environment id"), (operating_system, "operating system"),
            (architecture, "architecture"), (hardware_class, "hardware class"),
            (attestor_id, "attestor id"),
        ):
            _check_id(value, label)
        for value, label in (
            (runtime_config_digest, "runtime config"),
            (dependency_lock_digest, "dependency lock"),
        ):
            _check_digest(value, label)
        if attestation_level not in _ALLOWED_ATTESTATION_LEVELS:
            raise ExecutionProvenanceError("unsupported environment attestation level")
        digest = _digest(_environment_payload(
            environment_id, operating_system, architecture, hardware_class,
            runtime_config_digest, dependency_lock_digest, attestation_level, attestor_id,
        ))
        signature = _sign(digest, sign_attestation, "environment attestation")
        _check_signature(digest, signature, verify_attestation_signature, "environment attestation")
        return ExecutionEnvironmentAttestation(
            environment_id, operating_system, architecture, hardware_class,
            runtime_config_digest, dependency_lock_digest, attestation_level,
            attestor_id, digest, signature,
        )


def verify_environment_attestation(attestation: ExecutionEnvironmentAttestation, *,
                                   verify_signature: Callable[[str, str], bool],
                                   require_hardware_signed: bool = False) -> bool:
    if not isinstance(attestation, ExecutionEnvironmentAttestation) or attestation.proposal_only is not True:
        return False
    if attestation.attestation_level not in _ALLOWED_ATTESTATION_LEVELS:
        return False
    if require_hardware_signed and attestation.attestation_level != "hardware_signed":
        return False
    payload = _environment_payload(
        attestation.environment_id, attestation.operating_system, attestation.architecture,
        attestation.hardware_class, attestation.runtime_config_digest,
        attestation.dependency_lock_digest, attestation.attestation_level,
        attestation.attestor_id,
    )
    if _digest(payload) != attestation.environment_digest:
        return False
    try:
        _check_signature(attestation.environment_digest, attestation.signature,
                         verify_signature, "environment attestation")
    except ExecutionProvenanceError:
        return False
    return True


@dataclass(frozen=True)
class BoundExecutionEvidence:
    suite_digest: str
    run_digest: str
    candidate_id: str
    artifact_digest: str
    model_runtime_manifest_digest: str
    dataset_manifest_digest: str
    dataset_digest: str
    environment_digest: str
    attestation_level: str
    executor_id: str
    evaluator_id: str
    nonce: str
    binding_digest: str
    signature: str
    proposal_only: bool = True


def _binding_payload(*, suite_digest: str, run_digest: str, candidate_id: str,
                     artifact_digest: str, model_runtime_manifest_digest: str,
                     dataset_manifest_digest: str, dataset_digest: str,
                     environment_digest: str, attestation_level: str,
                     executor_id: str, evaluator_id: str, nonce: str) -> dict:
    return {
        "suite_digest": suite_digest, "run_digest": run_digest,
        "candidate_id": candidate_id, "artifact_digest": artifact_digest,
        "model_runtime_manifest_digest": model_runtime_manifest_digest,
        "dataset_manifest_digest": dataset_manifest_digest, "dataset_digest": dataset_digest,
        "environment_digest": environment_digest, "attestation_level": attestation_level,
        "executor_id": executor_id, "evaluator_id": evaluator_id, "nonce": nonce,
        "proposal_only": True,
    }


class Stage199ExecutionEvidenceBinder:
    """Cryptographically bind run, model, dataset, environment, and signer identities."""

    def build(self, suite: FrozenBenchmarkSuite, run: BenchmarkRunEvidence, *,
              model_manifest: ModelRuntimeManifest,
              dataset_manifest: DatasetProvenanceManifest,
              environment: ExecutionEnvironmentAttestation,
              verify_suite_signature: Callable[[str, str], bool],
              verify_run_signature: Callable[[str, str], bool],
              verify_model_signature: Callable[[str, str], bool],
              verify_dataset_signature: Callable[[str, str], bool],
              verify_environment_signature: Callable[[str, str], bool],
              sign_binding: Callable[[str], str],
              verify_binding_signature: Callable[[str, str], bool],
              nonce: str, require_hardware_signed: bool = False,
              hold_active: bool = False) -> BoundExecutionEvidence:
        _hold(hold_active, 199)
        if not all(hasattr(suite, name) for name in ("suite_id", "version", "cases", "suite_digest", "signature", "frozen")) or suite.frozen is not True:
            raise ExecutionProvenanceError("suite is not frozen")
        suite_payload = {
            "suite_id": suite.suite_id, "version": suite.version,
            "cases": [asdict(row) for row in suite.cases], "frozen": True,
        }
        if _digest(suite_payload) != suite.suite_digest:
            raise ExecutionProvenanceError("suite digest mismatch")
        _check_signature(suite.suite_digest, suite.signature, verify_suite_signature, "suite")
        if not all(hasattr(run, name) for name in ("suite_digest", "candidate_id", "artifact_digest", "run_id", "executor_id", "evaluator_id", "results", "run_digest", "signature")) or run.proposal_only is not True:
            raise ExecutionProvenanceError("run evidence is invalid")
        run_payload = {
            "suite_digest": run.suite_digest, "candidate_id": run.candidate_id,
            "artifact_digest": run.artifact_digest, "run_id": run.run_id,
            "executor_id": run.executor_id, "evaluator_id": run.evaluator_id,
            "results": [asdict(row) for row in run.results], "proposal_only": True,
        }
        if _digest(run_payload) != run.run_digest:
            raise ExecutionProvenanceError("run evidence digest mismatch")
        _check_signature(run.run_digest, run.signature, verify_run_signature, "run")
        if run.suite_digest != suite.suite_digest:
            raise ExecutionProvenanceError("run/suite digest mismatch")
        if run.candidate_id != model_manifest.candidate_id or run.artifact_digest != model_manifest.artifact_digest:
            raise ExecutionProvenanceError("run/model artifact identity mismatch")
        if not verify_model_runtime_manifest(model_manifest, verify_signature=verify_model_signature):
            raise ExecutionProvenanceError("model/runtime manifest invalid")
        if not verify_dataset_provenance(dataset_manifest, verify_signature=verify_dataset_signature):
            raise ExecutionProvenanceError("dataset provenance invalid")
        if not verify_environment_attestation(
            environment, verify_signature=verify_environment_signature,
            require_hardware_signed=require_hardware_signed,
        ):
            raise ExecutionProvenanceError("environment attestation invalid or insufficient")
        _check_id(nonce, "nonce")
        if run.executor_id == run.evaluator_id:
            raise ExecutionProvenanceError("executor and evaluator must be distinct")
        payload = _binding_payload(
            suite_digest=suite.suite_digest, run_digest=run.run_digest,
            candidate_id=run.candidate_id, artifact_digest=run.artifact_digest,
            model_runtime_manifest_digest=model_manifest.manifest_digest,
            dataset_manifest_digest=dataset_manifest.manifest_digest,
            dataset_digest=dataset_manifest.dataset_digest,
            environment_digest=environment.environment_digest,
            attestation_level=environment.attestation_level,
            executor_id=run.executor_id, evaluator_id=run.evaluator_id, nonce=nonce,
        )
        digest = _digest(payload)
        signature = _sign(digest, sign_binding, "execution evidence binding")
        _check_signature(digest, signature, verify_binding_signature, "execution evidence binding")
        return BoundExecutionEvidence(
            suite.suite_digest, run.run_digest, run.candidate_id, run.artifact_digest,
            model_manifest.manifest_digest, dataset_manifest.manifest_digest,
            dataset_manifest.dataset_digest, environment.environment_digest,
            environment.attestation_level, run.executor_id, run.evaluator_id,
            nonce, digest, signature,
        )


@dataclass(frozen=True)
class ExecutionProvenanceCertificate:
    suite_digest: str
    run_digest: str
    candidate_id: str
    artifact_digest: str
    model_runtime_manifest_digest: str
    dataset_manifest_digest: str
    dataset_digest: str
    environment_digest: str
    attestation_level: str
    executor_id: str
    evaluator_id: str
    nonce: str
    binding_digest: str
    certificate_digest: str
    signature: str
    proposal_only: bool = True
    model_activation_authorized: bool = False
    weight_mutation_authorized: bool = False
    merge_deploy_authorized: bool = False


def _certificate_payload(binding: BoundExecutionEvidence) -> dict:
    return {
        "suite_digest": binding.suite_digest, "run_digest": binding.run_digest,
        "candidate_id": binding.candidate_id, "artifact_digest": binding.artifact_digest,
        "model_runtime_manifest_digest": binding.model_runtime_manifest_digest,
        "dataset_manifest_digest": binding.dataset_manifest_digest,
        "dataset_digest": binding.dataset_digest, "environment_digest": binding.environment_digest,
        "attestation_level": binding.attestation_level, "executor_id": binding.executor_id,
        "evaluator_id": binding.evaluator_id, "nonce": binding.nonce,
        "binding_digest": binding.binding_digest, "proposal_only": True,
        "model_activation_authorized": False, "weight_mutation_authorized": False,
        "merge_deploy_authorized": False,
    }


class Stage200ExecutionProvenanceGate:
    """Issue a review-only certificate from a valid, fully bound execution record."""

    def build(self, binding: BoundExecutionEvidence, *,
              verify_binding_signature: Callable[[str, str], bool],
              sign_certificate: Callable[[str], str],
              verify_certificate_signature: Callable[[str, str], bool],
              require_hardware_signed: bool = False,
              hold_active: bool = False) -> ExecutionProvenanceCertificate:
        _hold(hold_active, 200)
        if not isinstance(binding, BoundExecutionEvidence) or binding.proposal_only is not True:
            raise ExecutionProvenanceError("bound execution evidence is invalid")
        if binding.attestation_level not in _ALLOWED_ATTESTATION_LEVELS:
            raise ExecutionProvenanceError("unknown environment assurance level")
        if require_hardware_signed and binding.attestation_level != "hardware_signed":
            raise ExecutionProvenanceError("hardware-signed environment evidence required")
        if binding.executor_id == binding.evaluator_id:
            raise ExecutionProvenanceError("executor and evaluator must be distinct")
        _check_id(binding.nonce, "nonce")
        payload = _binding_payload(
            suite_digest=binding.suite_digest, run_digest=binding.run_digest,
            candidate_id=binding.candidate_id, artifact_digest=binding.artifact_digest,
            model_runtime_manifest_digest=binding.model_runtime_manifest_digest,
            dataset_manifest_digest=binding.dataset_manifest_digest,
            dataset_digest=binding.dataset_digest, environment_digest=binding.environment_digest,
            attestation_level=binding.attestation_level, executor_id=binding.executor_id,
            evaluator_id=binding.evaluator_id, nonce=binding.nonce,
        )
        if _digest(payload) != binding.binding_digest:
            raise ExecutionProvenanceError("execution binding digest mismatch")
        _check_signature(binding.binding_digest, binding.signature,
                         verify_binding_signature, "execution binding")
        digest = _digest(_certificate_payload(binding))
        signature = _sign(digest, sign_certificate, "execution provenance certificate")
        _check_signature(digest, signature, verify_certificate_signature,
                         "execution provenance certificate")
        return ExecutionProvenanceCertificate(
            binding.suite_digest, binding.run_digest, binding.candidate_id,
            binding.artifact_digest, binding.model_runtime_manifest_digest,
            binding.dataset_manifest_digest, binding.dataset_digest,
            binding.environment_digest, binding.attestation_level,
            binding.executor_id, binding.evaluator_id, binding.nonce,
            binding.binding_digest, digest, signature,
        )


def verify_stage200_certificate(certificate: ExecutionProvenanceCertificate, *,
                                verify_signature: Callable[[str, str], bool],
                                require_hardware_signed: bool = False) -> bool:
    if not isinstance(certificate, ExecutionProvenanceCertificate):
        return False
    if (certificate.proposal_only is not True
            or certificate.model_activation_authorized is not False
            or certificate.weight_mutation_authorized is not False
            or certificate.merge_deploy_authorized is not False):
        return False
    if certificate.attestation_level not in _ALLOWED_ATTESTATION_LEVELS:
        return False
    if require_hardware_signed and certificate.attestation_level != "hardware_signed":
        return False
    if certificate.executor_id == certificate.evaluator_id:
        return False
    try:
        _check_id(certificate.nonce, "nonce")
        binding_payload = _binding_payload(
            suite_digest=certificate.suite_digest, run_digest=certificate.run_digest,
            candidate_id=certificate.candidate_id, artifact_digest=certificate.artifact_digest,
            model_runtime_manifest_digest=certificate.model_runtime_manifest_digest,
            dataset_manifest_digest=certificate.dataset_manifest_digest,
            dataset_digest=certificate.dataset_digest, environment_digest=certificate.environment_digest,
            attestation_level=certificate.attestation_level, executor_id=certificate.executor_id,
            evaluator_id=certificate.evaluator_id, nonce=certificate.nonce,
        )
        if _digest(binding_payload) != certificate.binding_digest:
            return False
        cert_payload = {
            **binding_payload, "binding_digest": certificate.binding_digest,
            "model_activation_authorized": False, "weight_mutation_authorized": False,
            "merge_deploy_authorized": False,
        }
        if _digest(cert_payload) != certificate.certificate_digest:
            return False
        _check_signature(certificate.certificate_digest, certificate.signature,
                         verify_signature, "execution provenance certificate")
        return True
    except (ExecutionProvenanceError, TypeError, ValueError):
        return False
